"""Durable notification delivery reservations and local receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260916_0015"
down_revision = "20260916_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("channels", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("triggers", sa.ARRAY(sa.String()), nullable=False),
    )
    op.add_column("notification_events", sa.Column("lease_token", postgresql.UUID(as_uuid=True)))
    op.create_index("ix_notification_due", "notification_events", ["status", "next_attempt_at"])
    op.create_table(
        "local_notification_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "notification_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("local_notification_receipts")
    op.drop_index("ix_notification_due", table_name="notification_events")
    op.drop_column("notification_events", "lease_token")
