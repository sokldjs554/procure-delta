"""Add extraction input provenance and durable identity without rewriting history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260916_0006"
down_revision = "20260916_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("structured_extractions", sa.Column("extraction_key", sa.String(64)))
    op.add_column("structured_extractions", sa.Column("input_fingerprint", sa.String(64)))
    for name in ("input_bundle_json", "conflicts_json"):
        op.add_column(
            "structured_extractions",
            sa.Column(name, postgresql.JSONB(), nullable=False, server_default="{}"),
        )
        op.alter_column("structured_extractions", name, server_default=None)
    # Legacy rows have no grounded input snapshot: retain but quarantine them.
    op.execute(
        "UPDATE structured_extractions SET extraction_key = md5(id::text) || md5(id::text), input_fingerprint = md5(id::text) || md5(id::text), validation_status = 'legacy_unverified'"
    )
    op.alter_column("structured_extractions", "extraction_key", nullable=False)
    op.alter_column("structured_extractions", "input_fingerprint", nullable=False)
    op.create_unique_constraint(
        "uq_extraction_identity",
        "structured_extractions",
        ["opportunity_version_id", "extraction_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_extraction_identity", "structured_extractions", type_="unique")
    for name in ("conflicts_json", "input_bundle_json", "input_fingerprint", "extraction_key"):
        op.drop_column("structured_extractions", name)
