from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContractProcessSnapshot, OpportunityVersion
from app.sources.koneps_process import ContractProcessPage, ContractProcessQuery


def query_for_service_record_id(
    source_record_id: str, *, inquiry_div: str
) -> ContractProcessQuery:
    pieces = source_record_id.split(":")
    if len(pieces) != 3 or pieces[0] != "services":
        raise ValueError("contract-process lookup requires a KONEPS service notice version")
    return ContractProcessQuery(
        inquiry_div=inquiry_div,
        bid_ntce_no=pieces[1],
        bid_ntce_ord=pieces[2],
    )


def query_for_service_version(
    version: OpportunityVersion, *, inquiry_div: str
) -> ContractProcessQuery:
    return query_for_service_record_id(version.source_record_id, inquiry_div=inquiry_div)


async def persist_contract_process_pages(
    session: AsyncSession,
    *,
    opportunity_version_id: UUID,
    query: ContractProcessQuery,
    pages: Sequence[ContractProcessPage],
) -> int:
    await session.get_one(OpportunityVersion, opportunity_version_id)
    created = 0
    public_query = query.public_parameters()
    for page in pages:
        statement = (
            insert(ContractProcessSnapshot)
            .values(
                opportunity_version_id=opportunity_version_id,
                inquiry_div=query.inquiry_div,
                query_fingerprint=query.fingerprint(),
                query_json=public_query,
                page_no=page.page_no,
                total_count=page.total_count,
                response_sha256=page.body_sha256,
                raw_body_json=page.raw_body,
                identifiers_json={
                    key: list(values) for key, values in page.identifiers.items()
                },
            )
            .on_conflict_do_nothing(constraint="uq_contract_process_snapshot")
            .returning(ContractProcessSnapshot.id)
        )
        created += int((await session.execute(statement)).scalar_one_or_none() is not None)
    await session.flush()
    return created
