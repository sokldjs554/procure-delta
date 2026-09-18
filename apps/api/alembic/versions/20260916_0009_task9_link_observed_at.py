"""Timestamp lifecycle decision revisions for later as-of reconstruction."""

import sqlalchemy as sa

from alembic import op

revision = "20260916_0009"
down_revision = "20260916_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows receive this migration's execution time; no historic time is inferred.
    op.add_column(
        "lifecycle_links",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.alter_column("lifecycle_links", "created_at", nullable=False)


def downgrade() -> None:
    op.drop_column("lifecycle_links", "created_at")
