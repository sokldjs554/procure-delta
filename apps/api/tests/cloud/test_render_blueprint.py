from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]


def _blueprint() -> dict:
    return yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))


def _env(service: dict) -> dict[str, dict]:
    return {
        row["key"]: row
        for row in service.get("envVars", [])
        if isinstance(row, dict) and "key" in row
    }


def test_render_blueprint_has_split_services_and_private_data_resources() -> None:
    data = _blueprint()
    services = {row["name"]: row for row in data["services"]}

    assert set(services) == {
        "procure-delta-api",
        "procure-delta-worker",
        "procure-delta-scheduler",
        "procure-delta-web",
        "procure-delta-cache",
    }
    assert services["procure-delta-api"]["healthCheckPath"] == "/health/live"
    assert services["procure-delta-api"]["preDeployCommand"] == "alembic upgrade head"
    assert services["procure-delta-cache"]["type"] == "keyvalue"
    assert services["procure-delta-cache"]["ipAllowList"] == []
    assert services["procure-delta-cache"]["maxmemoryPolicy"] == "noeviction"

    database = data["databases"][0]
    assert database["name"] == "procure-delta-db"
    assert database["postgresMajorVersion"] == "16"
    assert database["ipAllowList"] == []


def test_render_blueprint_wires_database_cache_storage_and_ci_gate() -> None:
    data = _blueprint()
    services = {row["name"]: row for row in data["services"]}

    for name in ("procure-delta-api", "procure-delta-worker", "procure-delta-scheduler"):
        service = services[name]
        env = _env(service)

        assert service["runtime"] == "docker"
        assert service["autoDeployTrigger"] == "checksPass"
        assert service["dockerfilePath"] == "./apps/api/Dockerfile"
        assert service["dockerContext"] == "./apps/api"
        assert env["DATABASE_URL"]["fromDatabase"] == {
            "name": "procure-delta-db",
            "property": "connectionString",
        }
        assert env["REDIS_URL"]["fromService"] == {
            "name": "procure-delta-cache",
            "type": "keyvalue",
            "property": "connectionString",
        }
        assert env["ATTACHMENT_STORAGE_BACKEND"]["value"] == "s3"
        for key in (
            "ATTACHMENT_S3_BUCKET",
            "ATTACHMENT_S3_REGION",
            "ATTACHMENT_S3_ENDPOINT_URL",
            "ATTACHMENT_S3_ACCESS_KEY_ID",
            "ATTACHMENT_S3_SECRET_ACCESS_KEY",
        ):
            assert env[key]["sync"] is False


def test_render_workers_wait_for_schema_and_web_requires_public_api_url() -> None:
    data = _blueprint()
    services = {row["name"]: row for row in data["services"]}

    assert "wait_for_schema" in services["procure-delta-worker"]["dockerCommand"]
    assert "wait_for_schema" in services["procure-delta-scheduler"]["dockerCommand"]

    web = services["procure-delta-web"]
    web_env = _env(web)
    assert web["autoDeployTrigger"] == "checksPass"
    assert web["dockerfilePath"] == "./apps/web/Dockerfile"
    assert web["dockerContext"] == "./apps/web"
    assert web_env["NEXT_PUBLIC_STATIC_DEMO"]["value"] == "false"
    assert web_env["NEXT_PUBLIC_API_URL"]["sync"] is False
