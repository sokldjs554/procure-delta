"""Version deterministic ranking inputs and explanations."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260916_0014"
down_revision = "20260916_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_ranking_company_version", "ranking_results", type_="unique")
    op.add_column(
        "ranking_results", sa.Column("eligibility_result_id", postgresql.UUID(as_uuid=True))
    )
    op.add_column(
        "ranking_results",
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ranking_results",
        sa.Column(
            "feature_breakdown_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("ranking_results", sa.Column("input_fingerprint", sa.String(64)))
    op.add_column(
        "ranking_results",
        sa.Column(
            "input_provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("ranking_results", sa.Column("as_of", sa.DateTime(timezone=True)))
    op.add_column("ranking_results", sa.Column("evaluation_epoch", sa.String(100)))
    op.execute(
        "UPDATE ranking_results SET input_fingerprint = repeat('0', 64), "
        "as_of = created_at, evaluation_epoch = 'legacy'"
    )
    op.alter_column("ranking_results", "input_fingerprint", nullable=False)
    op.alter_column("ranking_results", "as_of", nullable=False)
    op.alter_column("ranking_results", "evaluation_epoch", nullable=False)
    op.create_foreign_key(
        "fk_ranking_eligibility",
        "ranking_results",
        "eligibility_results",
        ["eligibility_result_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_ranking_inputs",
        "ranking_results",
        ["company_profile_id", "opportunity_version_id", "ranking_version", "input_fingerprint"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_ranking_inputs", "ranking_results", type_="unique")
    op.drop_constraint("fk_ranking_eligibility", "ranking_results", type_="foreignkey")
    for column in (
        "evaluation_epoch",
        "as_of",
        "input_provenance_json",
        "input_fingerprint",
        "feature_breakdown_json",
        "recommended",
        "eligibility_result_id",
    ):
        op.drop_column("ranking_results", column)
    op.create_unique_constraint(
        "uq_ranking_company_version",
        "ranking_results",
        ["company_profile_id", "opportunity_version_id", "ranking_version"],
    )
