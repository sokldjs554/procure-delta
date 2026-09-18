"""Use wall-clock lifecycle decision timestamps after graph-lock acquisition."""

import sqlalchemy as sa

from alembic import op

revision = "20260916_0010"
down_revision = "20260916_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "lifecycle_links",
        "created_at",
        server_default=sa.text("clock_timestamp()"),
    )


def downgrade() -> None:
    op.alter_column(
        "lifecycle_links",
        "created_at",
        server_default=sa.text("now()"),
    )
