"""Capture current transitions, processing readiness and immutable delta revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260916_0011"
down_revision = "20260916_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opportunity_versions", sa.Column("previous_current_version_id", sa.UUID()))
    op.create_foreign_key(
        "fk_version_previous_current",
        "opportunity_versions",
        "opportunity_versions",
        ["previous_current_version_id"],
        ["id"],
    )
    op.add_column(
        "opportunity_versions",
        sa.Column("transition_kind", sa.String(20), nullable=False, server_default="unknown"),
    )
    for column in ("transition_at", "documents_discovered_at", "documents_completed_at"):
        op.add_column("opportunity_versions", sa.Column(column, sa.DateTime(timezone=True)))
    op.add_column(
        "opportunity_versions",
        sa.Column(
            "document_gaps_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "opportunity_deltas",
        sa.Column("ruleset_version", sa.String(100), nullable=False, server_default="legacy"),
    )
    op.add_column("opportunity_deltas", sa.Column("input_fingerprint", sa.String(64)))
    op.add_column(
        "opportunity_deltas",
        sa.Column(
            "input_provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "opportunity_deltas",
        sa.Column("comparison_kind", sa.String(30), nullable=False, server_default="unknown"),
    )
    op.create_unique_constraint(
        "uq_delta_pair_input",
        "opportunity_deltas",
        ["from_version_id", "to_version_id", "ruleset_version", "input_fingerprint"],
    )
    op.create_check_constraint(
        "ck_delta_distinct_versions", "opportunity_deltas", "from_version_id <> to_version_id"
    )
    for side in ("from", "to"):
        op.create_foreign_key(
            f"fk_delta_{side}_owner",
            "opportunity_deltas",
            "opportunity_versions",
            ["opportunity_id", f"{side}_version_id"],
            ["opportunity_id", "id"],
        )


def downgrade() -> None:
    for side in ("from", "to"):
        op.drop_constraint(f"fk_delta_{side}_owner", "opportunity_deltas", type_="foreignkey")
    op.drop_constraint("ck_delta_distinct_versions", "opportunity_deltas", type_="check")
    op.drop_constraint("uq_delta_pair_input", "opportunity_deltas", type_="unique")
    for column in (
        "comparison_kind",
        "input_provenance_json",
        "input_fingerprint",
        "ruleset_version",
    ):
        op.drop_column("opportunity_deltas", column)
    op.drop_constraint("fk_version_previous_current", "opportunity_versions", type_="foreignkey")
    for column in (
        "document_gaps_json",
        "documents_completed_at",
        "documents_discovered_at",
        "transition_at",
        "transition_kind",
        "previous_current_version_id",
    ):
        op.drop_column("opportunity_versions", column)
