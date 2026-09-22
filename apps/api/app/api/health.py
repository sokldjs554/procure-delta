from __future__ import annotations

import asyncio
from importlib.metadata import version
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Response
from sqlalchemy import text

from app.api.auth import Redis, Session
from app.api.schemas import DTO
from app.config import get_settings
from app.documents.storage import configured_attachment_store
from app.extraction.hosted import configured_extractor

router = APIRouter(tags=["health"])


class Release(DTO):
    name: str
    version: str
    revision: str
    authentication: str
    extraction_mode: str


class Readiness(DTO):
    status: str
    dependencies: dict[str, bool]


@router.get("/api/v1/release", response_model=Release)
async def release() -> Release:
    settings = get_settings()
    return Release(
        name=settings.app_name,
        version=version("procure-delta-api"),
        revision=settings.release_revision,
        authentication="synthetic-demo-nonproduction",
        extraction_mode=settings.extraction_mode,
    )


@router.get("/health/ready", response_model=Readiness)
async def ready(session: Session, redis: Redis, response: Response) -> Readiness:
    checks = {
        "database": False,
        "schema": False,
        "redis": False,
        "worker": False,
        "scheduler": False,
        "storage": False,
        "extraction_config": False,
    }
    try:
        async with asyncio.timeout(3):
            await session.execute(text("SELECT 1"))
            checks["database"] = True
            revisions = set(
                (await session.scalars(text("SELECT version_num FROM alembic_version"))).all()
            )
            root = Path(__file__).resolve().parents[2]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "alembic"))
            checks["schema"] = revisions == set(ScriptDirectory.from_config(config).get_heads())
    except Exception:
        await session.rollback()
    try:
        async with asyncio.timeout(3):
            checks["redis"] = bool(await redis.ping())
            checks["worker"] = bool(await redis.exists("arq:procure-delta:worker:health-check"))
            checks["scheduler"] = bool(
                await redis.exists("arq:procure-delta:scheduler:health-check")
            )
    except Exception:
        pass
    try:
        async with asyncio.timeout(3):
            checks["storage"] = await configured_attachment_store(get_settings()).ready()
    except (OSError, ValueError):
        pass
    try:
        configured_extractor(get_settings())
        checks["extraction_config"] = True
    except ValueError:
        pass
    okay = all(checks.values())
    response.status_code = 200 if okay else 503
    return Readiness(status="ready" if okay else "not_ready", dependencies=checks)
