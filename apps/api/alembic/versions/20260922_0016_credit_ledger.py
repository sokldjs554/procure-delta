"""Credit reservation and immutable usage ledger."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260922_0016"
down_revision = "20260916_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("available_credits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reserved_credits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "available_credits >= 0", name="ck_credit_account_available_nonnegative"
        ),
        sa.CheckConstraint(
            "reserved_credits >= 0", name="ck_credit_account_reserved_nonnegative"
        ),
    )
    op.create_index("ix_credit_accounts_owner_user_id", "credit_accounts", ["owner_user_id"])

    op.create_table(
        "credit_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("credit_accounts.id"),
            nullable=False,
        ),
        sa.Column("reservation_key", sa.String(255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="reserved"),
        sa.Column("reference_type", sa.String(100), nullable=False),
        sa.Column("reference_key", sa.String(255), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("account_id", "reservation_key", name="uq_credit_reservation_key"),
        sa.CheckConstraint("amount > 0", name="ck_credit_reservation_amount_positive"),
        sa.CheckConstraint(
            "status IN ('reserved', 'committed', 'refunded')",
            name="ck_credit_reservation_status",
        ),
    )
    op.create_index("ix_credit_reservations_account_id", "credit_reservations", ["account_id"])

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("credit_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("credit_reservations.id"),
        ),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("reference_type", sa.String(100), nullable=False),
        sa.Column("reference_key", sa.String(255), nullable=False),
        sa.Column("available_after", sa.Integer(), nullable=False),
        sa.Column("reserved_after", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_credit_ledger_idempotency"),
        sa.CheckConstraint("amount > 0", name="ck_credit_ledger_amount_positive"),
        sa.CheckConstraint(
            "operation IN ('grant', 'reserve', 'commit', 'refund')",
            name="ck_credit_ledger_operation",
        ),
        sa.CheckConstraint("available_after >= 0", name="ck_credit_ledger_available_nonnegative"),
        sa.CheckConstraint("reserved_after >= 0", name="ck_credit_ledger_reserved_nonnegative"),
    )
    op.create_index("ix_credit_ledger_entries_account_id", "credit_ledger_entries", ["account_id"])
    op.create_index(
        "ix_credit_ledger_account_created",
        "credit_ledger_entries",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("credit_ledger_entries")
    op.drop_table("credit_reservations")
    op.drop_table("credit_accounts")
