from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.billing.service import register_customer
from tests.conftest import API_ROOT, TEST_DATABASE_URL


def configuration():
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    return config


def test_existing_budget_balances_survive_discriminator_migration():
    config = configuration()
    engine = create_engine(TEST_DATABASE_URL)
    command.downgrade(config, "20260922_0016")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO credit_accounts (id, owner_user_id, available_credits, reserved_credits)
                VALUES (:id, 'pre-migration-budget', 37, 11)
            """), {"id": uuid4()})
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT account_kind, available_credits, reserved_credits FROM credit_accounts
                WHERE owner_user_id = 'pre-migration-budget'
            """)).one() == ("internal_budget", 37, 11)
    finally:
        command.upgrade(config, "head")
        engine.dispose()


@pytest.mark.asyncio
async def test_downgrade_cannot_promote_sandbox_balances(worker_session_factory):
    async with worker_session_factory.begin() as session:
        await register_customer(session, scope="migration-test", customer_id="cus_migration")
    with pytest.raises(DBAPIError):
        command.downgrade(configuration(), "20260922_0016")
