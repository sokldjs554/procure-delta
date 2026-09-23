from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ContractProcessSnapshot,
    Opportunity,
    OpportunityVersion,
    RawRecord,
    SourceRegistry,
)
from app.services.contract_process import (
    persist_contract_process_pages,
    query_for_service_version,
)
from app.sources.koneps_process import ContractProcessPage


@pytest.mark.asyncio
async def test_contract_process_snapshot_is_append_only_and_idempotent(
    session: AsyncSession,
) -> None:
    source = SourceRegistry(
        code="koneps-services",
        display_name="KONEPS services",
        base_url="https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
    )
    session.add(source)
    await session.flush()
    raw = RawRecord(
        source_id=source.id,
        source_record_id="services:R26BK99990001:000",
        payload_json={"bidNtceNo": "R26BK99990001", "bidNtceOrd": "000"},
        payload_sha256="a" * 64,
        normalization_status="normalized",
    )
    opportunity = Opportunity(
        canonical_key="contract-process-test",
        title="Synthetic lifecycle lookup",
        buyer_name="Example Agency",
        lifecycle_stage="tender",
    )
    session.add_all([raw, opportunity])
    await session.flush()
    version = OpportunityVersion(
        opportunity_id=opportunity.id,
        raw_record_id=raw.id,
        version_number=1,
        source_record_id=raw.source_record_id,
        effective_at=datetime(2026, 9, 23, tzinfo=UTC),
        normalized_json={},
        normalized_sha256="b" * 64,
    )
    session.add(version)
    await session.flush()

    query = query_for_service_version(version, inquiry_div="1")
    first = ContractProcessPage(
        page_no=1,
        num_rows=100,
        total_count=1,
        raw_body={
            "pageNo": "1",
            "numOfRows": "100",
            "totalCount": "1",
            "process": {"bidNtceNo": "R26BK99990001", "bfSpecRgstNo": "337425"},
        },
        body_sha256="c" * 64,
        identifiers={
            "bidNtceNo": ("R26BK99990001",),
            "bfSpecRgstNo": ("337425",),
        },
    )
    assert (
        await persist_contract_process_pages(
            session,
            opportunity_version_id=version.id,
            query=query,
            pages=[first],
        )
        == 1
    )
    assert (
        await persist_contract_process_pages(
            session,
            opportunity_version_id=version.id,
            query=query,
            pages=[first],
        )
        == 0
    )

    changed = ContractProcessPage(
        page_no=1,
        num_rows=100,
        total_count=1,
        raw_body={**first.raw_body, "process": {"bidNtceNo": "R26BK99990001"}},
        body_sha256="d" * 64,
        identifiers={"bidNtceNo": ("R26BK99990001",)},
    )
    assert (
        await persist_contract_process_pages(
            session,
            opportunity_version_id=version.id,
            query=query,
            pages=[changed],
        )
        == 1
    )

    assert (
        await session.scalar(select(func.count()).select_from(ContractProcessSnapshot))
        == 2
    )
    rows = list(
        await session.scalars(
            select(ContractProcessSnapshot).order_by(ContractProcessSnapshot.response_sha256)
        )
    )
    assert rows[0].query_json == {
        "inqryDiv": "1",
        "bidNtceNo": "R26BK99990001",
        "bidNtceOrd": "000",
    }
    assert "serviceKey" not in rows[0].query_json
    assert rows[0].identifiers_json["bfSpecRgstNo"] == ["337425"]


def test_contract_process_query_only_accepts_koneps_service_versions() -> None:
    version = OpportunityVersion(
        opportunity_id=None,  # type: ignore[arg-type]
        raw_record_id=None,  # type: ignore[arg-type]
        version_number=1,
        source_record_id="mock:1",
        normalized_json={},
        normalized_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="KONEPS service notice"):
        query_for_service_version(version, inquiry_div="1")
