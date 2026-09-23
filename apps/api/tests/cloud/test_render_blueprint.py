from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BLUEPRINT = (ROOT / "render.yaml").read_text(encoding="utf-8")


def test_render_blueprint_has_split_services_and_private_data_resources() -> None:
    for name in (
        "procure-delta-api",
        "procure-delta-worker",
        "procure-delta-scheduler",
        "procure-delta-web",
        "procure-delta-cache",
        "procure-delta-db",
    ):
        assert f"name: {name}" in BLUEPRINT

    assert "type: keyvalue" in BLUEPRINT
    assert "maxmemoryPolicy: noeviction" in BLUEPRINT
    assert 'postgresMajorVersion: "16"' in BLUEPRINT
    assert BLUEPRINT.count("ipAllowList: []") >= 2


def test_render_blueprint_wires_database_cache_storage_and_ci_gate() -> None:
    assert BLUEPRINT.count("autoDeployTrigger: checksPass") == 4
    assert BLUEPRINT.count("dockerfilePath: ./apps/api/Dockerfile") == 3
    assert BLUEPRINT.count("dockerContext: ./apps/api") == 3
    assert "preDeployCommand: alembic upgrade head" in BLUEPRINT
    assert "property: connectionString" in BLUEPRINT
    assert BLUEPRINT.count("key: ATTACHMENT_STORAGE_BACKEND") == 3
    assert BLUEPRINT.count("value: s3") >= 3

    for key in (
        "ATTACHMENT_S3_BUCKET",
        "ATTACHMENT_S3_REGION",
        "ATTACHMENT_S3_ENDPOINT_URL",
        "ATTACHMENT_S3_ACCESS_KEY_ID",
        "ATTACHMENT_S3_SECRET_ACCESS_KEY",
    ):
        assert BLUEPRINT.count(f"key: {key}") == 3


def test_render_workers_wait_for_schema_and_web_uses_same_origin_proxy() -> None:
    assert BLUEPRINT.count("python -m app.ops.wait_for_schema") == 2
    assert "dockerfilePath: ./apps/web/Dockerfile" in BLUEPRINT
    assert "dockerContext: ./apps/web" in BLUEPRINT
    assert "key: NEXT_PUBLIC_STATIC_DEMO" in BLUEPRINT
    assert 'key: NEXT_PUBLIC_API_URL\n        value: ""' in BLUEPRINT
    assert "key: API_PROXY_ORIGIN\n        sync: false" in BLUEPRINT
    assert BLUEPRINT.count("sync: false") >= 15


def test_render_blueprint_wires_optional_sentry_settings() -> None:
    assert BLUEPRINT.count("key: SENTRY_ENABLED") == 3
    assert BLUEPRINT.count("key: SENTRY_DSN") == 3
    assert BLUEPRINT.count("key: SENTRY_ENVIRONMENT") == 3
    assert BLUEPRINT.count("key: SENTRY_TRACES_SAMPLE_RATE") == 3
    assert BLUEPRINT.count("value: production") >= 3
