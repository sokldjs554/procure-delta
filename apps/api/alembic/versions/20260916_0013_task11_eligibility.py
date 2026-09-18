"""Version company profiles and eligibility inputs."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260916_0013"
down_revision = "20260916_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_company_profiles_owner", "company_profiles", ["owner_user_id"])
    op.add_column("company_profiles", sa.Column("contract_currency", sa.String(3)))
    op.add_column("eligibility_results", sa.Column("profile_input_fingerprint", sa.String(64)))
    op.add_column("eligibility_results", sa.Column("opportunity_input_fingerprint", sa.String(64)))
    op.add_column(
        "eligibility_results",
        sa.Column(
            "input_provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "eligibility_results",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "UPDATE eligibility_results SET profile_input_fingerprint = repeat('0', 64), "
        "opportunity_input_fingerprint = repeat('0', 64)"
    )
    op.alter_column("eligibility_results", "profile_input_fingerprint", nullable=False)
    op.alter_column("eligibility_results", "opportunity_input_fingerprint", nullable=False)
    op.alter_column("eligibility_results", "created_at", nullable=False)
    op.create_unique_constraint(
        "uq_eligibility_inputs",
        "eligibility_results",
        [
            "company_profile_id",
            "opportunity_version_id",
            "ruleset_version",
            "profile_input_fingerprint",
            "opportunity_input_fingerprint",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_eligibility_inputs", "eligibility_results", type_="unique")
    for column in (
        "created_at",
        "input_provenance_json",
        "opportunity_input_fingerprint",
        "profile_input_fingerprint",
    ):
        op.drop_column("eligibility_results", column)
    op.drop_column("company_profiles", "contract_currency")
    op.drop_constraint("uq_company_profiles_owner", "company_profiles", type_="unique")
