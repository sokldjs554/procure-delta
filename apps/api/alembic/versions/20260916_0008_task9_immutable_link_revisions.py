"""Allow immutable lifecycle decision revisions while retaining one active parent."""

from alembic import op

revision = "20260916_0008"
down_revision = "20260916_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_lifecycle_link_edge", "lifecycle_links", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_lifecycle_link_edge",
        "lifecycle_links",
        ["parent_opportunity_id", "child_opportunity_id", "child_version_id", "relation_type"],
    )
