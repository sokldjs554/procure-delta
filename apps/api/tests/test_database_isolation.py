from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import SourceRegistry


@pytest.mark.asyncio
async def test_01_committed_worker_data_is_written(worker_session_factory) -> None:
    async with worker_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SourceRegistry)) == 0
        session.add(
            SourceRegistry(
                code="isolation-probe",
                display_name="Isolation probe",
                base_url="https://example.invalid",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_02_previous_test_committed_worker_data_is_removed(worker_session_factory) -> None:
    async with worker_session_factory() as session:
        result = await session.scalar(
            select(SourceRegistry).where(SourceRegistry.code == "isolation-probe")
        )
        assert result is None
