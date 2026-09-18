"""Add the durable current-state effective-time watermark."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260916_0004"
down_revision: str | None = "20260916_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("current_effective_at", sa.DateTime(timezone=True)))
    op.execute(
        """
        UPDATE opportunities AS opportunity
        SET current_effective_at = version.effective_at
        FROM opportunity_versions AS version
        WHERE version.id = opportunity.current_version_id
        """
    )


def downgrade() -> None:
    op.drop_column("opportunities", "current_effective_at")
