"""Qualify document completion across native-parse recovery commits."""

import sqlalchemy as sa

from alembic import op

revision = "20260916_0012"
down_revision = "20260916_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opportunity_versions", sa.Column("documents_generation", sa.UUID()))


def downgrade() -> None:
    op.drop_column("opportunity_versions", "documents_generation")
