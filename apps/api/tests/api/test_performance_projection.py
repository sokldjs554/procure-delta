from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import performance
from app.main import app


@pytest.mark.asyncio
async def test_engineering_evidence_exposes_measured_values_and_scope() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/engineering-evidence")

    assert response.status_code == 200
    body = response.json()
    assert body["cpu"]["status"] == "measured"
    assert body["cpu"]["synthetic"] is True
    assert body["cpu"]["normalized_records"] == 50000
    assert body["cpu"]["delta_pairs"] == 5000
    assert body["cpu"]["scope"] == "cpu_only_production_functions"
    assert body["failure_drill"]["scope"] == "http_transport_injection"
    assert body["release"]["passed"] is True
    assert body["release"]["readiness"] == "ready"


@pytest.mark.asyncio
async def test_engineering_evidence_missing_artifacts_are_not_reported_as_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(performance, "ARTIFACT_ROOT", tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/engineering-evidence")

    assert response.status_code == 200
    body = response.json()
    assert body["cpu"]["status"] == "not_run"
    assert body["failure_drill"]["status"] == "not_run"
    assert body["release"]["status"] == "not_run"
    assert body["queue"]["status"] == "not_run"
    assert body["http"]["status"] == "not_run"
    assert body["query_plans"]["status"] == "not_run"


def test_artifact_root_resolution_is_safe_in_shallow_container_layout(tmp_path: Path) -> None:
    fake_module = tmp_path / "app" / "api" / "performance.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("# synthetic module path", encoding="utf-8")

    root = performance.resolve_artifact_root(fake_module)

    assert root == tmp_path / "artifacts"


@pytest.mark.asyncio
async def test_engineering_evidence_projects_committed_service_measurements() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/evaluation/engineering-evidence")

    assert response.status_code == 200
    body = response.json()

    assert body["queue"]["status"] == "measured"
    assert body["queue"]["scope"] == "real_redis_arq_postgresql"
    assert body["queue"]["metrics"]["records"] == 1000
    assert body["queue"]["metrics"]["completed_records"] == 1000
    assert body["queue"]["metrics"]["successful"] is True

    assert body["http"]["status"] == "measured"
    assert body["http"]["scope"] == "real_local_http"
    assert body["http"]["metrics"]["requests"] == 200
    assert body["http"]["metrics"]["failed_requests"] == 0
    assert body["http"]["metrics"]["endpoints"]["inbox"]["p95_ms"] > 0

    assert body["query_plans"]["status"] == "measured"
    assert body["query_plans"]["scope"] == "real_postgresql_explain"
    assert body["query_plans"]["metrics"]["candidate_adopted"] is False
    assert body["query_plans"]["metrics"]["candidate_rolled_back"] is True
    assert body["query_plans"]["metrics"]["improvement_ratio"] > 1
