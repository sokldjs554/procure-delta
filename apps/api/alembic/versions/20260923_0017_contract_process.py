"""Append-only KONEPS contract-process lookup snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260923_0017"
down_revision = "20260922_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_process_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "opportunity_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("opportunity_versions.id"),
            nullable=False,
        ),
        sa.Column("inquiry_div", sa.String(20), nullable=False),
        sa.Column("query_fingerprint", sa.String(64), nullable=False),
        sa.Column("query_json", postgresql.JSONB(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("response_sha256", sa.String(64), nullable=False),
        sa.Column("raw_body_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "identifiers_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.UniqueConstraint(
            "opportunity_version_id",
            "query_fingerprint",
            "page_no",
            "response_sha256",
            name="uq_contract_process_snapshot",
        ),
        sa.CheckConstraint("page_no >= 1", name="ck_contract_process_page_positive"),
        sa.CheckConstraint(
            "total_count >= 0", name="ck_contract_process_total_nonnegative"
        ),
    )
    op.create_index(
        "ix_contract_process_snapshots_opportunity_version_id",
        "contract_process_snapshots",
        ["opportunity_version_id"],
    )
    op.create_index(
        "ix_contract_process_version_fetched",
        "contract_process_snapshots",
        ["opportunity_version_id", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_table("contract_process_snapshots")
