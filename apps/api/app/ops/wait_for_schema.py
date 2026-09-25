from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.config import get_settings


def schema_ready() -> bool:
    settings = get_settings()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            observed: set[str] = set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
        return observed == expected
    finally:
        engine.dispose()


def wait_for_schema(
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 2.0,
    checker: Callable[[], bool] = schema_ready,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if checker():
                return
        except Exception:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("database schema did not become ready")
        time.sleep(interval_seconds)


def main() -> None:
    wait_for_schema()


if __name__ == "__main__":
    main()
