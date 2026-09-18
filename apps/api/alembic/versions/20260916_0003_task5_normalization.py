"""Add durable normalization state and version provenance."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260916_0003"
down_revision: str | None = "20260916_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "raw_records",
        sa.Column("normalization_status", sa.String(length=50), server_default="pending", nullable=False),
    )
    op.add_column("raw_records", sa.Column("normalized_at", sa.DateTime(timezone=True)))
    op.add_column("raw_records", sa.Column("normalized_version_id", sa.UUID()))
    op.create_index("ix_raw_records_normalization_status", "raw_records", ["normalization_status"])
    op.add_column("opportunity_versions", sa.Column("raw_record_id", sa.UUID()))
    op.create_foreign_key(
        "fk_opportunity_version_raw", "opportunity_versions", "raw_records", ["raw_record_id"], ["id"]
    )
    op.create_unique_constraint("uq_opportunity_version_raw", "opportunity_versions", ["raw_record_id"])
    op.create_foreign_key(
        "fk_raw_record_normalized_version",
        "raw_records",
        "opportunity_versions",
        ["normalized_version_id"],
        ["id"],
        use_alter=True,
    )
    op.alter_column("opportunity_versions", "raw_record_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_raw_record_normalized_version", "raw_records", type_="foreignkey")
    op.drop_constraint("uq_opportunity_version_raw", "opportunity_versions", type_="unique")
    op.drop_constraint("fk_opportunity_version_raw", "opportunity_versions", type_="foreignkey")
    op.drop_column("opportunity_versions", "raw_record_id")
    op.drop_index("ix_raw_records_normalization_status", table_name="raw_records")
    op.drop_column("raw_records", "normalized_version_id")
    op.drop_column("raw_records", "normalized_at")
    op.drop_column("raw_records", "normalization_status")
