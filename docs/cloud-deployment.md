# Cloud deployment contract

ProcureDelta includes a Render reference Blueprint in `render.yaml`. This file is deployment-readiness evidence, not proof that the full backend stack is currently operating in the cloud.

The repository keeps three scopes separate:

- public portfolio demo: read-only synthetic Next.js experience
- CI release gate: real FastAPI, PostgreSQL, Redis/ARQ and browser integration in isolated containers
- Render Blueprint: declarative API, web, worker, scheduler, Postgres and Key Value topology for a future cloud sync

## Shared attachment storage

The document worker downloads and parses attachments, while the API later serves the original checksum blob. Separate cloud services cannot safely depend on one local filesystem.

When `ATTACHMENT_STORAGE_BACKEND=s3`, both processes use the same S3-compatible object store. Local Docker Compose keeps the filesystem backend as its default.

The content-addressed key remains:

    sha256/<first-two-hex>/<full-sha256>.blob

Reads are bounded by `ATTACHMENT_MAX_BYTES`, storage keys are validated before access, and the API verifies the bytes against the database SHA-256 before serving them.

## Render topology

The reference Blueprint declares:

- procure-delta-api: Docker web service, migration pre-deploy, /health/live
- procure-delta-worker: ARQ worker
- procure-delta-scheduler: ARQ scheduler
- procure-delta-web: Next.js Docker service
- procure-delta-db: managed PostgreSQL 16
- procure-delta-cache: private Key Value service with noeviction policy

Git-backed services use `autoDeployTrigger: checksPass`.

Database and Key Value connection strings are injected with Render resource references instead of being committed. S3 credentials, CORS origin, and the public API URL are entered during Blueprint setup with `sync: false`.

Workers run `python -m app.ops.wait_for_schema` before ARQ. They do not assume the API service has already finished its migration.

Render supplies Postgres connection strings in `postgresql://...` form. ProcureDelta normalizes that boundary to the installed SQLAlchemy psycopg dialect for both the application and Alembic.

## What this does not prove

The Blueprint has not been synced to create a full backend stack in the user's Render workspace. Therefore this is deployment-readiness evidence, not cloud-operation evidence.

A real cloud verification would still require:

1. syncing the Blueprint and reviewing any billable resources,
2. providing the S3-compatible bucket, region, endpoint if needed, and credentials,
3. setting the API CORS origin and the web build-time public API URL,
4. enabling the KONEPS source only with a real service key,
5. waiting for /health/ready to report database, schema, redis, worker, scheduler, storage, and extraction_config as ready,
6. inspecting logs and metrics during a real collection window,
7. exercising rollback and redeploy behavior.

CI intentionally does not create these cloud resources automatically.
