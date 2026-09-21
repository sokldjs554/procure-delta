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
