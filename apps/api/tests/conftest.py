from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://procure_delta:procure_delta@localhost:5432/procure_delta_task4_test",
)
ADMIN_DATABASE_URL = os.getenv(
    "TEST_ADMIN_DATABASE_URL", "postgresql://procure_delta:procure_delta@localhost:5432/postgres"
)
API_ROOT = Path(__file__).parents[1]


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, object]:
    """Use a selector loop because psycopg async does not support Proactor on Windows."""
    del config, item
    return {"selector": asyncio.SelectorEventLoop if os.name == "nt" else asyncio.new_event_loop}


def _test_database_name() -> str:
    test_url = make_url(TEST_DATABASE_URL)
    admin_url = make_url(ADMIN_DATABASE_URL)
    database_name = test_url.database
    if database_name is None or not (
        database_name.endswith("_test") or database_name.startswith("procure_delta_test_")
    ):
        raise RuntimeError("TEST_DATABASE_URL must target a dedicated *_test database")
    if database_name in {"postgres", "template0", "template1", "procure_delta"}:
        raise RuntimeError("TEST_DATABASE_URL must not target an application or system database")
    if (test_url.host, test_url.port) != (admin_url.host, admin_url.port):
        raise RuntimeError("TEST_ADMIN_DATABASE_URL must use the same PostgreSQL host and port")
    return database_name


def _migrated_database() -> Iterator[None]:
    database = sql.Identifier(_test_database_name())
    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database))
        connection.execute(sql.SQL("CREATE DATABASE {}").format(database))
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(config, "head")
    yield
    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database))


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    yield from _migrated_database()


def _truncate_committed_test_data() -> None:
    """Reset every application table in the dedicated test database.

    A fresh synchronous connection avoids depending on any test event loop or worker
    session that may have committed independently. The database name is guarded by
    ``_test_database_name`` before this function is ever used.
    """
    _test_database_name()
    test_url = make_url(TEST_DATABASE_URL)
    dsn = test_url.set(drivername="postgresql").render_as_string(hide_password=False)
    table_names = [table.name for table in Base.metadata.sorted_tables]
    if not table_names:
        return
    identifiers = sql.SQL(", ").join([sql.Identifier(name) for name in table_names])
    statement = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(identifiers)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(statement)


@pytest.fixture(autouse=True)
def isolate_committed_test_data() -> Iterator[None]:
    """Give every test a clean database even after independent commits or failures."""
    _truncate_committed_test_data()
    try:
        yield
    finally:
        _truncate_committed_test_data()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with factory() as database_session:
            yield database_session
            await database_session.rollback()
        if transaction.is_active:
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def worker_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
