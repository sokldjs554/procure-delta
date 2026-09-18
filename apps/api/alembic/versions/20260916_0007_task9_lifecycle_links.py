"""Constrain lifecycle links to idempotent directed non-self edges."""

import sqlalchemy as sa

from alembic import op

revision = "20260916_0007"
down_revision = "20260916_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lifecycle_links", sa.Column("parent_version_id", sa.Uuid()))
    op.add_column("lifecycle_links", sa.Column("child_version_id", sa.Uuid()))
    op.add_column(
        "lifecycle_links",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column("lifecycle_links", sa.Column("retracted_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_lifecycle_parent_version",
        "lifecycle_links",
        "opportunity_versions",
        ["parent_version_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_lifecycle_child_version",
        "lifecycle_links",
        "opportunity_versions",
        ["child_version_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_lifecycle_link_not_self",
        "lifecycle_links",
        "parent_opportunity_id <> child_opportunity_id",
    )
    op.create_unique_constraint(
        "uq_lifecycle_link_edge",
        "lifecycle_links",
        ["parent_opportunity_id", "child_opportunity_id", "child_version_id", "relation_type"],
    )
    op.create_index(
        "uq_lifecycle_active_child",
        "lifecycle_links",
        ["child_opportunity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_lifecycle_active_child", table_name="lifecycle_links")
    op.drop_constraint("uq_lifecycle_link_edge", "lifecycle_links", type_="unique")
    op.drop_constraint("ck_lifecycle_link_not_self", "lifecycle_links", type_="check")
    op.drop_constraint("fk_lifecycle_child_version", "lifecycle_links", type_="foreignkey")
    op.drop_constraint("fk_lifecycle_parent_version", "lifecycle_links", type_="foreignkey")
    for name in ("retracted_at", "status", "child_version_id", "parent_version_id"):
        op.drop_column("lifecycle_links", name)
