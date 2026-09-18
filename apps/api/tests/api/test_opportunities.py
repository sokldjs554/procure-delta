import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Opportunity, OpportunityVersion, RawRecord, SourceRegistry


@pytest_asyncio.fixture
async def client(session, monkeypatch, tmp_path):
    from arq.connections import ArqRedis

    from app.api import admin, auth

    namespace = "task14:" + uuid4().hex + ":"
    queue = namespace + "worker"
    monkeypatch.setattr(auth, "PREFIX", namespace)
    monkeypatch.setattr(admin, "WORKER_QUEUE", queue)
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15"))
    # Added settings are set without requiring an implementation import in the RED run.
    monkeypatch.setattr(
        settings, "demo_operator_secret", SecretStr("test-operator-secret"), raising=False
    )
    monkeypatch.setattr(settings, "attachment_storage_path", tmp_path)

    async def database():
        yield session

    app.dependency_overrides[get_session] = database
    transport = ASGITransport(app=app, client=(uuid4().hex, 123))
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()
    redis = ArqRedis.from_url(settings.redis_url)
    jobs = await redis.zrange(queue, 0, -1)
    keys = [key async for key in redis.scan_iter(match=namespace + "*")]
    keys += [b"arq:job:" + job for job in jobs]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()


async def login(client, operator=False):
    response = await client.post(
        "/api/v1/auth/demo-login",
        json={"operator_secret": "test-operator-secret"} if operator else {},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


@pytest_asyncio.fixture
async def opportunities(session):
    source = SourceRegistry(
        code="api-" + uuid4().hex, display_name="Synthetic", base_url="https://example.invalid"
    )
    session.add(source)
    await session.flush()
    rows = []
    now = datetime.now(UTC)
    for index in range(4):
        raw = RawRecord(
            source_id=source.id,
            source_record_id=str(index),
            payload_sha256=str(index) * 64,
            payload_json={},
        )
        row = Opportunity(
            canonical_key=source.code + str(index),
            title=f"Synthetic cloud {index}",
            buyer_name=source.code,
            procurement_type="services",
            lifecycle_stage="tender",
            estimated_amount=Decimal(100 + index),
            published_at=now - timedelta(days=1),
            closes_at=now + timedelta(days=index + 1),
            status="open",
        )
        session.add_all([raw, row])
        await session.flush()
        version = OpportunityVersion(
            opportunity_id=row.id,
            raw_record_id=raw.id,
            version_number=1,
            source_record_id=str(index),
            effective_at=now - timedelta(days=1),
            normalized_sha256="a" * 64,
            normalized_json={"title": row.title},
            transition_kind="initial",
            documents_completed_at=now,
            documents_discovered_at=now,
        )
        session.add(version)
        await session.flush()
        row.current_version_id = version.id
        rows.append(row)
    await session.flush()
    return rows


@pytest.mark.asyncio
async def test_anonymous_cannot_read_profile_or_spoof_owner(session):
    async def database():
        yield session

    app.dependency_overrides[get_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get(
            "/api/v1/company-profile", headers={"X-Demo-Owner": "synthetic-demo-owner"}
        )
        app.dependency_overrides.clear()
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_session_csrf_roles_and_isolated_owners(client):
    actor = await login(client)
    assert actor["role"] == "user" and actor["synthetic_demo"] is True
    assert (
        "HttpOnly" in client.cookies.jar._cookies["test.local"]["/"]["procure_delta_session"]._rest
    )
    assert (await client.get("/api/v1/auth/session")).json()["owner_id"] == actor["owner_id"]
    assert (await client.get("/api/v1/company-profile")).json()["synthetic_demo"] is True
    assert (await client.get("/api/v1/admin/pipeline")).status_code == 403
    assert (
        await client.patch(
            "/api/v1/company-profile",
            json={"display_name": "Synthetic renamed"},
            headers={"X-CSRF-Token": "wrong"},
        )
    ).status_code == 403
    assert (
        await client.patch("/api/v1/company-profile", json={"owner_user_id": "victim"})
    ).status_code == 422
    assert (
        await client.patch(
            "/api/v1/company-profile",
            json={"display_name": "Synthetic renamed"},
            headers={"Origin": "https://evil.invalid"},
        )
    ).status_code == 403
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    other = await login(client)
    assert other["owner_id"] != actor["owner_id"]


@pytest.mark.asyncio
async def test_keyset_filters_detail_and_current_ranking(client, opportunities):
    await login(client)
    buyer = opportunities[0].buyer_name
    first = await client.get("/api/v1/opportunities", params={"buyer": buyer, "limit": 2})
    assert first.status_code == 200, first.text
    page = first.json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    second = (
        await client.get(
            "/api/v1/opportunities",
            params={"buyer": buyer, "limit": 2, "cursor": page["next_cursor"]},
        )
    ).json()
    assert len(second["items"]) == 2 and second["next_cursor"] is None
    assert len({item["id"] for item in page["items"] + second["items"]}) == 4
    filtered = (
        await client.get(
            "/api/v1/opportunities",
            params={
                "buyer": buyer,
                "amount_min": 102,
                "amount_max": 102,
                "status": "open",
                "lifecycle_stage": "tender",
                "category": "services",
                "q": "cloud",
                "deadline_from": opportunities[2].closes_at.isoformat(),
                "deadline_to": opportunities[2].closes_at.isoformat(),
            },
        )
    ).json()
    assert [item["id"] for item in filtered["items"]] == [str(opportunities[2].id)]
    assert (
        await client.get("/api/v1/opportunities", params={"cursor": "invalid"})
    ).status_code == 422
    assert (
        await client.get("/api/v1/opportunities", params={"amount_min": 100, "amount_max": 1})
    ).status_code == 422
    detail = (await client.get(f"/api/v1/opportunities/{opportunities[0].id}")).json()
    assert detail["eligibility"]["warnings"]
    assert detail["ranking"]["recommended"] is False
    assert detail["versions"][0]["id"] == str(opportunities[0].current_version_id)
    assert detail["timeline"]["active_links"] == []
    assert detail["extraction"]["status"] == "no_suitable_pages"
    assert detail["documents"] == []


@pytest.mark.asyncio
async def test_watch_preferences_and_history_ownership(client, opportunities):
    first = await login(client)
    path = f"/api/v1/opportunities/{opportunities[0].id}/watch"
    assert (await client.post(path)).status_code == 200
    assert (await client.post(path)).status_code == 200
    assert len((await client.get("/api/v1/watchlist")).json()["items"]) == 1
    assert (
        await client.put("/api/v1/notifications/preferences", json={"enabled": False})
    ).status_code == 200
    assert (await client.get("/api/v1/notifications/preferences")).json()["enabled"] is False
    await client.post("/api/v1/auth/logout")
    second = await login(client)
    assert first["owner_id"] != second["owner_id"]
    assert (await client.get("/api/v1/watchlist")).json()["items"] == []
    assert (await client.get("/api/v1/notifications")).json()["items"] == []
    assert (await client.delete(path)).status_code == 204


@pytest.mark.asyncio
async def test_eligible_scan_continuation_never_repeats_or_loses_late_matches(
    client, session, monkeypatch
):
    from app.api import opportunities as api
    from app.api.schemas import Eligibility, OpportunitySummary

    await login(client)
    buyer = "scan-" + uuid4().hex
    now = datetime.now(UTC)
    rows = [
        Opportunity(
            canonical_key=buyer + str(i),
            title="Synthetic",
            buyer_name=buyer,
            published_at=now - timedelta(seconds=i),
        )
        for i in range(205)
    ]
    session.add_all(rows)
    await session.flush()
    matches = {row.id for row in rows[200:]}

    async def summary(session, row, owner, profile):
        result = OpportunitySummary.model_validate(row)
        result.eligibility = Eligibility(
            id=uuid4(),
            eligible=row.id in matches,
            hard_failures=[],
            warnings=[],
            ruleset_version="test",
        )
        return result

    monkeypatch.setattr(api, "summarize", summary)
    seen = []
    cursor = None
    for _ in range(10):
        params = {"buyer": buyer, "eligible_only": "true", "limit": 10}
        if cursor:
            params["cursor"] = cursor
        response = await client.get("/api/v1/opportunities", params=params)
        assert response.status_code == 200, response.text
        seen.extend(item["id"] for item in response.json()["items"])
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == {str(item) for item in matches}


@pytest.mark.asyncio
async def test_actual_source_timeout_keeps_normalized_feed_readable(
    client, session, opportunities, monkeypatch
):
    import httpx
    from arq import Retry

    from app.workers import jobs

    await login(client)
    buyer = opportunities[0].buyer_name
    before = (await client.get("/api/v1/opportunities", params={"buyer": buyer})).json()

    class Unavailable:
        async def discover(self, cursor):
            raise httpx.ReadTimeout("synthetic upstream outage")

    monkeypatch.setattr(jobs, "source_adapters", lambda: {buyer: Unavailable()})
    with pytest.raises(Retry):
        await jobs.poll_source({"session": session}, buyer)
    after = await client.get("/api/v1/opportunities", params={"buyer": buyer})
    assert after.status_code == 200
    assert [row["id"] for row in before["items"]] == [row["id"] for row in after.json()["items"]]


@pytest.mark.asyncio
async def test_original_documents_are_checksum_verified_and_never_remote_fetches(
    client, session, opportunities, tmp_path
):
    import hashlib

    from app.models import Attachment

    await login(client)
    content = b"synthetic original document"
    checksum = hashlib.sha256(content).hexdigest()
    key = f"sha256/{checksum[:2]}/{checksum}.blob"
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    attachment = Attachment(
        opportunity_version_id=opportunities[0].current_version_id,
        source_url="https://example.invalid/secret?token=hidden",
        filename="../../bad.html",
        media_type="text/html",
        sha256=checksum,
        storage_key=key,
        byte_size=len(content),
    )
    session.add(attachment)
    await session.flush()
    response = await client.get(f"/api/v1/documents/{attachment.id}/original")
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "application/octet-stream"
    assert "bad.html" not in response.headers["content-disposition"]
    path.write_bytes(b"corruption")
    assert (await client.get(f"/api/v1/documents/{attachment.id}/original")).status_code == 409
    attachment.storage_key = "../../outside"
    await session.flush()
    assert (await client.get(f"/api/v1/documents/{attachment.id}/original")).status_code == 404


@pytest.mark.asyncio
async def test_profile_edit_recomputes_eligibility_identity_and_demo_flag_is_enforced(
    client, opportunities
):
    await login(client)
    path = f"/api/v1/opportunities/{opportunities[0].id}"
    before = (await client.get(path)).json()
    changed = await client.patch(
        "/api/v1/company-profile", json={"excluded_keywords": ["Synthetic"]}
    )
    assert changed.status_code == 200
    after = (await client.get(path)).json()
    assert before["eligibility"]["id"] != after["eligibility"]["id"]
    assert (
        await client.patch("/api/v1/company-profile", json={"synthetic_demo": False})
    ).status_code == 422


@pytest.mark.asyncio
async def test_extraction_identity_rejections_conflicts_history_and_evidence(
    client,
    session,
    opportunities,
    tmp_path,
):
    from sqlalchemy import select

    from app.documents.service import persist_and_parse_attachments
    from app.extraction.deterministic import DeterministicExtractor
    from app.extraction.service import persist_extraction
    from app.models import Attachment, DocumentParse
    from app.sources.mock import MockSourceAdapter

    await login(client)
    row = opportunities[0]
    adapter = MockSourceAdapter()
    record = await adapter.fetch_record("synthetic-pre-spec-001")
    await persist_and_parse_attachments(
        session,
        opportunity_version_id=row.current_version_id,
        refs=await adapter.fetch_attachments(record),
        allowed_source_host="example.invalid",
        storage_root=tmp_path,
    )
    path = f"/api/v1/opportunities/{row.id}"
    before = (await client.get(path)).json()
    assert before["extraction"]["status"] == "pending"
    assert any(
        parsed["status"] == "trusted" for doc in before["documents"] for parsed in doc["parses"]
    )
    extracted = await persist_extraction(session, row.current_version_id, DeterministicExtractor())
    response = (await client.get(path)).json()
    assert response["extraction"]["status"] == "validated"
    assert "title" in response["extraction"]["conflicts"]
    assert "title" not in response["extraction"]["trusted_fields"]
    evidence = response["extraction"]["evidence"]["required_capabilities"][0]
    assert evidence["page_number"] >= 1 and evidence["quote"]
    assert any(
        doc["sha256"] == evidence["attachment_sha256"] and doc["original_url"]
        for doc in response["documents"]
    )
    parsed = await session.scalar(
        select(DocumentParse)
        .join(Attachment)
        .where(
            Attachment.opportunity_version_id == row.current_version_id,
            DocumentParse.status == "trusted",
        )
    )
    parsed.parser_version += "-changed"
    await session.flush()
    changed = (await client.get(path)).json()
    assert changed["extraction"]["status"] == "pending"
    history = await client.get(f"{path}/versions/{row.current_version_id}/extractions")
    assert history.status_code == 200, history.text
    snapshot = next(item for item in history.json() if item["id"] == str(extracted.id))
    assert snapshot["applicable_now"] is False and snapshot["status"] == "validated"
    rejected = await persist_extraction(session, row.current_version_id, DeterministicExtractor())
    rejected.validation_status = "rejected"
    rejected.validation_errors_json = {"errors": ["synthetic rejection"]}
    await session.flush()
    last = (await client.get(path)).json()["extraction"]
    assert last["status"] == "rejected" and last["trusted_fields"] == {}
    assert last["validation_errors"] == ["validation_failed"]


@pytest.mark.asyncio
async def test_timeline_excludes_retracted_branch_and_keeps_version_evidence(
    client, session, opportunities
):
    from app.models import LifecycleLink

    await login(client)
    a, b, c = opportunities[:3]
    common = {
        "relation_type": "pre_spec_to_tender",
        "confidence": Decimal("1"),
        "link_method": "official_reference",
        "evidence_json": {"synthetic": True},
    }
    active = LifecycleLink(
        parent_opportunity_id=a.id,
        child_opportunity_id=b.id,
        parent_version_id=a.current_version_id,
        child_version_id=b.current_version_id,
        status="active",
        **common,
    )
    retracted = LifecycleLink(
        parent_opportunity_id=b.id,
        child_opportunity_id=c.id,
        parent_version_id=b.current_version_id,
        child_version_id=c.current_version_id,
        status="retracted",
        **common,
    )
    session.add_all([active, retracted])
    await session.flush()
    result = (await client.get(f"/api/v1/opportunities/{a.id}/timeline")).json()
    assert set(result["opportunity_ids"]) == {str(a.id), str(b.id)}
    assert result["active_links"][0]["parent_version_id"] == str(a.current_version_id)
    assert result["historical_links"][0]["id"] == str(retracted.id)


@pytest.mark.asyncio
async def test_delta_repair_does_not_mark_old_finalization_current(client, session, opportunities):
    from app.delta.service import persist_delta
    from app.extraction.deterministic import DeterministicExtractor
    from app.models import Attachment

    await login(client)
    row = opportunities[0]
    previous = await session.get_one(OpportunityVersion, row.current_version_id)
    raw = await session.get_one(RawRecord, previous.raw_record_id)
    next_raw = RawRecord(source_id=raw.source_id, source_record_id="next", payload_sha256="f" * 64)
    session.add(next_raw)
    await session.flush()
    current = OpportunityVersion(
        opportunity_id=row.id,
        raw_record_id=next_raw.id,
        version_number=2,
        source_record_id="next",
        normalized_sha256="f" * 64,
        effective_at=datetime.now(UTC) - timedelta(hours=1),
        transition_kind="current",
        previous_current_version_id=previous.id,
        transition_at=datetime.now(UTC),
        documents_completed_at=datetime.now(UTC),
        documents_discovered_at=datetime.now(UTC),
    )
    session.add(current)
    await session.flush()
    row.current_version_id = current.id
    _, old = await persist_delta(session, current.id, DeterministicExtractor())
    await session.flush()
    current.documents_completed_at = None
    await session.flush()
    pending = (await client.get(f"/api/v1/opportunities/{row.id}/deltas")).json()
    assert pending["current_inputs_ready"] is False
    assert not any(item["applicable_now"] for item in pending["items"])
    current.documents_completed_at = datetime.now(UTC)
    session.add(
        Attachment(
            opportunity_version_id=current.id,
            source_url="https://example.invalid/new",
            filename="synthetic.unsupported",
            download_status="unsupported",
        )
    )
    await session.flush()
    repaired = (await client.get(f"/api/v1/opportunities/{row.id}/deltas")).json()
    assert repaired["current_inputs_ready"] is True
    old_view = next(item for item in repaired["items"] if item["id"] == str(old.id))
    assert old_view["applicable_now"] is False


@pytest.mark.asyncio
async def test_populated_notification_history_is_owner_scoped(client, session, opportunities):
    from app.models import LocalNotificationReceipt, NotificationEvent

    actor = await login(client)
    event = NotificationEvent(
        user_id=actor["owner_id"],
        opportunity_id=opportunities[0].id,
        channel="local",
        template_key="new_high_relevance",
        dedupe_key=uuid4().hex,
        status="sent",
        payload_json={"title": "Synthetic owned notification"},
    )
    session.add(event)
    await session.flush()
    receipt = LocalNotificationReceipt(
        notification_event_id=event.id, payload_json=event.payload_json
    )
    session.add(receipt)
    await session.flush()
    owned = (await client.get("/api/v1/notifications")).json()
    assert owned["items"][0]["receipt_id"] == str(receipt.id)
    await client.post("/api/v1/auth/logout")
    await login(client)
    other = await client.get("/api/v1/notifications", headers={"X-Demo-Owner": actor["owner_id"]})
    assert other.json()["items"] == []


@pytest.mark.asyncio
async def test_auth_rejects_forgery_and_disabled_operator_without_echoing_secret(
    client, monkeypatch
):
    assert (
        await client.post("/api/v1/auth/demo-login", json={"owner_id": "victim"})
    ).status_code == 422
    bad = await client.post(
        "/api/v1/auth/demo-login", json={"operator_secret": "wrong-private-password"}
    )
    assert bad.status_code == 401 and "wrong-private-password" not in bad.text
    monkeypatch.setattr(get_settings(), "demo_operator_secret", None)
    assert (
        await client.post(
            "/api/v1/auth/demo-login", json={"operator_secret": "test-operator-secret"}
        )
    ).status_code == 401
    actor = await login(client)
    same = await login(client)
    assert actor["owner_id"] == same["owner_id"]
    client.cookies.set("procure_delta_session", "forged", domain="test.local", path="/")
    assert (await client.get("/api/v1/company-profile")).status_code == 401


@pytest.mark.asyncio
async def test_pending_document_repair_withholds_prior_matching_decisions(
    client, session, opportunities
):
    await login(client)
    row = opportunities[0]
    path = f"/api/v1/opportunities/{row.id}"
    assert (await client.get(path)).json()["eligibility"] is not None
    version = await session.get_one(OpportunityVersion, row.current_version_id)
    version.documents_completed_at = None
    await session.flush()
    pending = (await client.get(path)).json()
    assert pending["eligibility"] is None and pending["ranking"] is None
    assert pending["decision_status"] == "documents_pending"


@pytest.mark.asyncio
async def test_public_provenance_replaces_transport_locations_without_mutating_history(
    client,
    session,
    opportunities,
):
    from copy import deepcopy

    from app.delta.service import persist_delta
    from app.extraction.deterministic import DeterministicExtractor
    from app.models import Attachment, NotificationEvent

    actor = await login(client)
    row = opportunities[0]
    before = await session.get_one(OpportunityVersion, row.current_version_id)
    raw = await session.get_one(RawRecord, before.raw_record_id)
    next_raw = RawRecord(
        source_id=raw.source_id, source_record_id="url-change", payload_sha256="f" * 64
    )
    session.add(next_raw)
    await session.flush()
    after = OpportunityVersion(
        opportunity_id=row.id,
        raw_record_id=next_raw.id,
        version_number=2,
        source_record_id="url-change",
        normalized_sha256="f" * 64,
        effective_at=datetime.now(UTC) - timedelta(hours=1),
        transition_kind="current",
        previous_current_version_id=before.id,
        transition_at=datetime.now(UTC),
        documents_completed_at=datetime.now(UTC),
        documents_discovered_at=datetime.now(UTC),
    )
    session.add(after)
    await session.flush()
    row.current_version_id = after.id
    urls = [
        "https://example.invalid/old?token=hidden-old",
        "https://user:hidden-user@example.invalid/new?token=hidden-new",
    ]
    attachments = [
        Attachment(
            opportunity_version_id=version.id,
            source_url=url,
            filename="synthetic.pdf",
            download_status="unsupported",
            sha256=checksum * 64,
            storage_key=f"sha256/{checksum * 2}/{checksum * 64}.blob",
        )
        for version, url, checksum in zip([before, after], urls, ["b", "c"], strict=True)
    ]
    session.add_all(attachments)
    await session.flush()
    quote = "Document quote: https://public.example/reference?section=two remains verbatim."
    after.normalized_json = {
        "title": "Synthetic URL amendment",
        "attachments": [
            {"url": urls[1], "metadata": {"headers": {"Authorization": "hidden-header"}}}
        ],
        "evidence": {
            "title": [
                {
                    "attachment_sha256": "c" * 64,
                    "page_number": 2,
                    "quote": quote,
                    "source_url": urls[1],
                    "metadata": {"nested": {"access_token": "hidden-nested"}},
                }
            ]
        },
    }
    await session.flush()
    original = deepcopy(after.normalized_json)
    _, delta = await persist_delta(session, after.id, DeterministicExtractor())
    stored_documents = deepcopy(delta.document_changes_json)
    event = NotificationEvent(
        user_id=actor["owner_id"],
        opportunity_id=row.id,
        delta_id=delta.id,
        channel="local",
        template_key="watched_material_change",
        dedupe_key=uuid4().hex,
        payload_json={
            "document_changes": deepcopy(stored_documents),
            "from_version_id": str(before.id),
            "to_version_id": str(after.id),
        },
    )
    session.add(event)
    await session.flush()
    path = f"/api/v1/opportunities/{row.id}"
    for endpoint in [path, path + "/deltas", "/api/v1/notifications"]:
        response = await client.get(endpoint)
        assert response.status_code == 200, response.text
        assert "hidden-" not in response.text
        assert "source_url" not in response.text
        assert f"/api/v1/documents/{attachments[1].id}/original" in response.text
    detail = (await client.get(path)).json()
    normalized = detail["versions"][0]["normalized_json"]
    assert normalized["attachments"][0]["attachment_id"] == str(attachments[1].id)
    assert normalized["evidence"]["title"][0]["quote"] == quote
    assert normalized["evidence"]["title"][0]["page_number"] == 2
    await session.refresh(after)
    await session.refresh(delta)
    await session.refresh(event)
    assert after.normalized_json == original
    assert delta.document_changes_json == stored_documents
    assert event.payload_json["document_changes"] == stored_documents


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_uuid", [1, {}, []])
async def test_cursor_rejects_non_string_uuid_elements(client, opportunities, invalid_uuid):
    import base64
    import json

    await login(client)
    params = {"buyer": opportunities[0].buyer_name, "limit": 1}
    page = (await client.get("/api/v1/opportunities", params=params)).json()
    decoded = json.loads(base64.urlsafe_b64decode(page["next_cursor"]))
    decoded[1] = invalid_uuid
    params["cursor"] = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode()
    response = await client.get("/api/v1/opportunities", params=params)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_historical_extraction_parse_link_and_ranking_project_nested_metadata(
    client,
    session,
    opportunities,
):
    from copy import deepcopy

    from app.models import (
        Attachment,
        DocumentParse,
        LifecycleLink,
        RankingResult,
        StructuredExtraction,
    )

    await login(client)
    row, other = opportunities[:2]
    path = f"/api/v1/opportunities/{row.id}"
    current = (await client.get(path)).json()
    quote = "Actual quote with https://public.example/path?token=literal-evidence is preserved."
    private = {
        "transport": [
            {
                "headers": {"Authorization": "hidden-authorization"},
                "url": "https://example.invalid?token=hidden-transport",
            }
        ]
    }
    evidence = {
        "title": [
            {
                "quote": quote,
                "page_number": 1,
                "attachment_sha256": "b" * 64,
                "source_url": "https://example.invalid?token=hidden-source",
                "metadata": private,
            }
        ]
    }
    attachment = Attachment(
        opportunity_version_id=row.current_version_id,
        filename="synthetic.pdf",
        source_url="https://example.invalid?token=hidden-source",
        sha256="b" * 64,
    )
    session.add(attachment)
    await session.flush()
    parsed = DocumentParse(
        attachment_id=attachment.id,
        parser_kind="native_pdf",
        parser_version="test",
        status="needs_ocr",
        quality_json={
            "pages": [{"page_number": 1, "text": quote, "metadata": private}],
            "metadata": private,
        },
    )
    extracted = StructuredExtraction(
        opportunity_version_id=row.current_version_id,
        extractor_version="test",
        schema_version="1",
        extraction_key="d" * 64,
        input_fingerprint="e" * 64,
        validation_status="rejected",
        validation_errors_json={"errors": ["input_value={'token': 'hidden-validation'}"]},
        output_json={"title": "Synthetic proposal", "evidence": evidence, "metadata": private},
    )
    link = LifecycleLink(
        parent_opportunity_id=row.id,
        child_opportunity_id=other.id,
        parent_version_id=row.current_version_id,
        child_version_id=other.current_version_id,
        relation_type="precedes",
        confidence=1,
        status="active",
        link_method="official_reference",
        evidence_json={
            "source_id": str(uuid4()),
            "source_record_id": "synthetic",
            "metadata": private,
        },
    )
    ranking = await session.get_one(RankingResult, UUID(current["ranking"]["id"]))
    ranking.explanation_json = {
        **ranking.explanation_json,
        "evidence": evidence,
        "metadata": private,
    }
    original_ranking = deepcopy(ranking.explanation_json)
    session.add_all([parsed, extracted, link])
    await session.flush()
    routes = [
        path,
        path + "/timeline",
        path + "/ranking",
        f"{path}/versions/{row.current_version_id}/documents",
        f"{path}/versions/{row.current_version_id}/extractions",
    ]
    for endpoint in routes:
        response = await client.get(endpoint)
        assert response.status_code == 200, response.text
        assert "hidden-" not in response.text and "metadata" not in response.text
    assert (await client.get(path + "/ranking")).json()["explanation"]["evidence"]["title"][0][
        "quote"
    ] == quote
    history = (await client.get(routes[-1])).json()
    assert history[0]["validation_errors"] == ["schema_validation_failed"]
    assert history[0]["proposal"]["evidence"]["title"][0]["quote"] == quote
    documents = (await client.get(routes[-2])).json()
    assert documents[0]["parses"][0]["quality_json"]["pages"][0]["text"] == quote
    await session.refresh(ranking)
    await session.refresh(extracted)
    assert ranking.explanation_json == original_ranking
    assert extracted.output_json["metadata"] == private
