"""Add a concurrency-safe identity for durable failed jobs."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0002"
down_revision: str | None = "43a24e2f8d9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_job_failure_type_key", "job_failures", ["job_type", "job_key"])


def downgrade() -> None:
    op.drop_constraint("uq_job_failure_type_key", "job_failures", type_="unique")
