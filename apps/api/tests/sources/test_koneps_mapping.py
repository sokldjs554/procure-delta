from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Opportunity, OpportunityVersion, RawRecord, SourceRegistry
from app.services.normalize import normalize_raw_record
from app.sources.http import ResilientHttpClient
from app.workers.jobs import ingest_record


def module() -> Any:
    assert importlib.util.find_spec("app.sources.koneps") is not None, "official adapter missing"
    return importlib.import_module("app.sources.koneps")


def fixture() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("fixtures").joinpath("koneps_services_synthetic.json")
        .read_text(encoding="utf-8")
    )["response"]


def raw_item() -> dict[str, Any]:
    return fixture()["body"]["items"][0]


@pytest.mark.asyncio
async def test_official_discovery_preserves_payload_and_freezes_pagination_window() -> None:
    api = module()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = fixture()
        response["body"].update(totalCount=2, numOfRows=1, pageNo=int(request.url.params["pageNo"]))
        return httpx.Response(200, json={"response": response}, headers={"etag": "revision"})

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
        adapter = api.KonepsSourceAdapter(service_key="synthetic+key=", client=client, page_size=1)
        page = await adapter.discover(None)
        next_page = await adapter.discover(page.next_cursor)
    assert page.records[0].raw_payload == raw_item()
    assert page.records[0].source_record_id == "services:R26BK99990001:000"
    assert page.records[0].http_etag == "revision"
    assert page.records[0].source_updated_at is None  # mapping happens after preservation
    assert next_page.next_cursor is not None
    assert [r.url.params["pageNo"] for r in requests] == ["1", "2"]
    assert requests[0].url.params["inqryBgnDt"] == requests[1].url.params["inqryBgnDt"]
    assert requests[0].url.params["serviceKey"] == "synthetic+key="
    assert requests[0].url.path == "/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"


def test_mapping_uses_original_evidence_unknown_restrictions_and_korean_time() -> None:
    api = module()
    raw = RawRecord(id=uuid4(), source_id=uuid4(), source_record_id="services:R26BK99990001:000",
                    payload_json=raw_item(), payload_sha256="a" * 64,
                    fetched_at=datetime(2026, 9, 16, tzinfo=UTC))
    normalized = normalize_raw_record(raw, source_code=api.SOURCE_CODE)
    assert normalized.title == "Synthetic cloud services tender"
    assert normalized.published_at == datetime(2026, 9, 15, tzinfo=UTC)
    assert normalized.closes_at == datetime(2026, 9, 30, 9, tzinfo=UTC)
    assert normalized.normalized_json["estimated_amount"] == "125000000"
    assert normalized.evidence["estimated_amount"][0]["json_pointer"] == "/presmptPrce"
    assert normalized.regions == () and normalized.required_certifications == ()
    assert "regions" not in normalized.evidence
    assert normalized.official_references == ()
    assert raw.payload_json == raw_item()


@pytest.mark.asyncio
async def test_persisted_official_replay_revision_and_late_arrival(session: AsyncSession) -> None:
    api = module()
    source = SourceRegistry(
        code=api.SOURCE_CODE, display_name="KONEPS services", base_url=api.BASE_URL
    )
    session.add(source)
    await session.commit()
    original = raw_item()
    payload = {"source_record_id": "services:R26BK99990001:000", "raw_payload": original}
    assert (await ingest_record({"session": session}, source.code, payload))["status"] == "created"
    replay = await ingest_record({"session": session}, source.code, payload)
    assert replay["status"] == "duplicate"
    changed = {**original, "bidNtceOrd": "001", "ntceKindNm": "변경공고",
               "chgDt": "2026-09-16 12:00:00", "bidClseDt": "2026-10-02 18:00:00"}
    await ingest_record({"session": session}, source.code,
                        {"source_record_id": "services:R26BK99990001:001", "raw_payload": changed})
    late = {**original, "bidNtceNm": "Synthetic earlier correction", "chgDt": "2026-09-15 10:00:00"}
    await ingest_record({"session": session}, source.code, {**payload, "raw_payload": late})
    assert await session.scalar(select(func.count()).select_from(RawRecord)) == 3
    assert await session.scalar(select(func.count()).select_from(Opportunity)) == 1
    assert await session.scalar(select(func.count()).select_from(OpportunityVersion)) == 3
    opportunity = (await session.scalars(select(Opportunity))).one()
    assert opportunity.lifecycle_stage == "amendment"
    assert opportunity.closes_at == datetime(2026, 10, 2, 9, tzinfo=UTC)
    raws = (await session.scalars(select(RawRecord))).all()
    assert any(r.payload_json == original for r in raws)
    assert all("title" not in r.payload_json for r in raws)


@pytest.mark.asyncio
async def test_attachments_are_real_references_without_fetch_or_fake_fixtures() -> None:
    api = module()
    from app.sources.base import RawSourceRecord

    adapter = api.KonepsSourceAdapter(service_key="synthetic-key")
    refs = await adapter.fetch_attachments(RawSourceRecord(
        source_record_id="services:R26BK99990001:000", raw_payload=raw_item()))
    assert len(refs) == 1
    assert refs[0].url == "https://www.g2b.go.kr/synthetic/spec.pdf"
    assert refs[0].fixture_key is None
    assert refs[0].filename == "synthetic-spec.pdf"


@pytest.mark.asyncio
async def test_configured_factory_and_scheduler_include_official_feed_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession,
) -> None:
    from app.config import Settings
    from app.workers import jobs

    assert set(jobs.source_adapters()) == {"mock"}
    monkeypatch.setattr(jobs, "get_settings", lambda: Settings(
        koneps_enabled=True, koneps_service_key="synthetic-key", _env_file=None))
    adapters = jobs.source_adapters()
    assert "koneps-services" in adapters
    assert hasattr(jobs, "poll_configured_sources"), "scheduler has no configured polling path"
    calls = []

    async def poll(ctx: Any, source_code: str = "mock") -> dict[str, str]:
        calls.append(source_code)
        return {"status": "success", "source": source_code}

    monkeypatch.setattr(jobs, "poll_source", poll)
    await jobs.poll_configured_sources({"session": session})
    assert calls == ["mock", "koneps-services"]


@pytest.mark.asyncio
async def test_poll_document_discovery_and_eligibility_use_original_fields(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, tmp_path: Path,
) -> None:
    api = module()
    from app.documents import download, service
    from app.documents.synthetic_fixtures import load_packaged_fixture
    from app.models import Attachment, DocumentParse
    from app.ranking.eligibility import _raw_claim
    from app.workers import jobs
    from app.workers.lifecycle import link_opportunity

    async with ResilientHttpClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": fixture()})
    )) as client:
        adapter = api.KonepsSourceAdapter(service_key="synthetic-key", client=client)
        monkeypatch.setattr(jobs, "source_adapters", lambda: {api.SOURCE_CODE: adapter})
        polled = await jobs.poll_source({"session": session}, api.SOURCE_CODE)
        assert polled["status"] == "success"
    source = (await session.scalars(select(SourceRegistry))).one()
    assert source.base_url == api.BASE_URL
    assert "Synthetic" not in source.display_name
    version = (await session.scalars(select(OpportunityVersion))).one()
    raw = await session.get_one(RawRecord, version.raw_record_id)
    claim = _raw_claim(raw, version, "estimated_amount")
    assert claim is not None and claim.evidence[0]["json_pointer"] == "/presmptPrce"
    assert claim.evidence[0]["raw_record_id"] == str(raw.id)
    assert _raw_claim(raw, version, "regions") is None
    linked = await link_opportunity({"session": session}, str(version.opportunity_id))
    assert linked["status"] == "unresolved"

    async def addresses(host: str) -> tuple[str, ...]:
        return ("8.8.8.8",)

    monkeypatch.setattr(download, "_resolve_public_addresses", addresses)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=load_packaged_fixture("synthetic-specification.pdf"),
        headers={"content-type": "application/pdf"},
    ))) as document_client:
        async def fetch(ref: Any, **kwargs: Any) -> Any:
            # The production service always forwards its optional client keyword, even when
            # it is None. Replace that value instead of passing a duplicate keyword.
            kwargs["client"] = document_client
            return await download.download_attachment(ref, **kwargs)

        monkeypatch.setattr(service, "download_attachment", fetch)
        result = await jobs.reconcile_pending_documents({"session": session,
                                                         "attachment_storage_path": tmp_path})
    from app.models import JobFailure
    failures = (await session.scalars(select(JobFailure))).all()
    errors = [(f.error_class, f.error_message) for f in failures]
    assert result == {"processed": 1, "failed": 0}, errors
    attachment = (await session.scalars(select(Attachment))).one()
    assert attachment.source_url == raw_item()["ntceSpecDocUrl1"]
    assert attachment.download_status == "parsed"
    assert await session.scalar(select(func.count()).select_from(DocumentParse)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 503])
async def test_failures_do_not_disclose_service_key_and_retry_only_transient_status(
    status: int, caplog: pytest.LogCaptureFixture,
) -> None:
    api = module()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, text="synthetic-secret-key")

    caplog.set_level("INFO")
    async with ResilientHttpClient(transport=httpx.MockTransport(handler),
                                   backoff_base_seconds=0) as client:
        adapter = api.KonepsSourceAdapter(service_key="synthetic-secret-key", client=client)
        with pytest.raises(httpx.HTTPStatusError) as error:
            await adapter.discover(None)
    assert attempts == (1 if status == 401 else 3)
    assert "synthetic-secret-key" not in str(error.value)
    assert "synthetic-secret-key" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"response": {"header": {"resultCode": "30", "resultMsg": "synthetic-secret"}}},
    {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": ""}}},
    {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": -1, "items": []}}},
])
async def test_api_errors_or_inconsistent_pages_cannot_advance_checkpoint(body: Any) -> None:
    api = module()
    async with ResilientHttpClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body)
    )) as client:
        with pytest.raises(ValueError):
            await api.KonepsSourceAdapter(service_key="synthetic-key", client=client).discover(None)


@pytest.mark.asyncio
async def test_fetch_record_selects_exact_order_and_registration_poll_then_change_poll() -> None:
    api = module()
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        body = fixture()
        body["body"]["items"].append({**raw_item(), "bidNtceOrd": "001"})
        body["body"]["totalCount"] = 2
        return httpx.Response(200, json={"response": body})

    async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
        adapter = api.KonepsSourceAdapter(service_key="synthetic-key", client=client)
        record = await adapter.fetch_record("services:R26BK99990001:001")
        first = await adapter.discover(None)
        second = await adapter.discover(first.next_cursor)
        await adapter.discover(second.next_cursor)
    assert record.raw_payload["bidNtceOrd"] == "001"
    assert calls[0]["bidNtceNo"] == "R26BK99990001"
    assert [item["inqryDiv"] for item in calls] == ["2", "1", "3", "1"]


@pytest.mark.parametrize("kind", ["등록공고", "재공고", "취소공고"])
def test_nonzero_order_is_not_sufficient_to_invent_amendment(kind: str) -> None:
    api = module()
    mapped = api.map_payload({**raw_item(), "bidNtceOrd": "002", "ntceKindNm": kind},
                             "services:R26BK99990001:002")
    assert mapped["lifecycle_stage"] == "tender"
