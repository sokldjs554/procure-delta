"""Isolated sandbox webhook observations and atomic invoice credit applications."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260927_0017"
down_revision = "20260922_0016"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                     server_default=sa.func.now())


def upgrade() -> None:
    op.add_column("credit_accounts", sa.Column("account_kind", sa.String(30), nullable=False,
                                               server_default="internal_budget"))
    op.create_check_constraint("ck_credit_account_kind", "credit_accounts",
                               "account_kind IN ('internal_budget', 'billing_sandbox')")
    op.execute("""
        CREATE FUNCTION prevent_credit_kind_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.account_kind IS DISTINCT FROM OLD.account_kind OR
             (OLD.account_kind = 'billing_sandbox' AND
              NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id) THEN
            RAISE EXCEPTION 'credit account kind and sandbox identity are immutable';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER credit_account_kind_immutable BEFORE UPDATE ON credit_accounts
          FOR EACH ROW EXECUTE FUNCTION prevent_credit_kind_mutation();
    """)
    op.create_table("billing_customer_mappings", _id(),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(200), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("credit_accounts.id"), nullable=False), _created(),
        sa.UniqueConstraint("scope", "customer_id", name="uq_billing_customer_scope"),
        sa.UniqueConstraint("account_id", name="uq_billing_customer_account"))
    op.create_table("billing_price_policies", _id(),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("price_id", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("credit_units", sa.Integer(), nullable=False), _created(),
        sa.UniqueConstraint("scope", "price_id", name="uq_billing_price_scope"),
        sa.CheckConstraint("amount > 0 AND credit_units > 0", name="ck_billing_price_positive"))
    op.create_table("billing_invoice_applications", _id(),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("invoice_id", sa.String(200), nullable=False),
        sa.Column("invoice_digest", sa.String(64), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("credit_accounts.id"), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("billing_price_policies.id"), nullable=False),
        sa.Column("credit_units", sa.Integer(), nullable=False),
        sa.Column("ledger_entry_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("credit_ledger_entries.id"), nullable=False),
        sa.Column("facts_json", postgresql.JSONB(), nullable=False), _created(),
        sa.UniqueConstraint("scope", "invoice_id", name="uq_billing_invoice_scope"),
        sa.UniqueConstraint("ledger_entry_id", name="uq_billing_invoice_ledger"),
        sa.CheckConstraint("credit_units > 0", name="ck_billing_application_units"))
    op.create_table("billing_event_observations", _id(),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_created", sa.BigInteger(), nullable=False),
        sa.Column("object_id", sa.String(200), nullable=False),
        sa.Column("customer_id", sa.String(200)),
        sa.Column("event_digest", sa.String(64), nullable=False),
        sa.Column("facts_json", postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("review_reason", sa.String(50)),
        sa.Column("application_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("billing_invoice_applications.id")), _created(),
        sa.UniqueConstraint("scope", "event_id", name="uq_billing_event_scope"),
        sa.CheckConstraint("outcome IN ('applied','duplicate','observed','review')",
                           name="ck_billing_event_outcome"))
    op.execute("""
        CREATE FUNCTION prevent_billing_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'sandbox billing records are immutable'; END; $$;
        CREATE FUNCTION require_sandbox_billing_account() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM credit_accounts WHERE id = NEW.account_id
                         AND account_kind = 'billing_sandbox') THEN
            RAISE EXCEPTION 'billing requires an isolated sandbox account';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER billing_customer_account_kind BEFORE INSERT ON billing_customer_mappings
          FOR EACH ROW EXECUTE FUNCTION require_sandbox_billing_account();
        CREATE TRIGGER billing_application_account_kind BEFORE INSERT ON billing_invoice_applications
          FOR EACH ROW EXECUTE FUNCTION require_sandbox_billing_account();
    """)
    for table in ("billing_customer_mappings", "billing_price_policies",
                  "billing_invoice_applications", "billing_event_observations"):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION prevent_billing_mutation()")


def downgrade() -> None:
    # Dropping the discriminator while sandbox balances exist would convert them
    # into spendable internal budgets. A populated sandbox requires explicit export
    # and a separate migration, never silent downgrade or deletion of its history.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM credit_accounts WHERE account_kind = 'billing_sandbox') THEN
            RAISE EXCEPTION 'cannot downgrade while sandbox credit accounts exist';
          END IF;
        END; $$;
    """)
    for table in ("billing_event_observations", "billing_invoice_applications",
                  "billing_price_policies", "billing_customer_mappings"):
        op.drop_table(table)
    op.execute("DROP FUNCTION prevent_billing_mutation()")
    op.execute("DROP FUNCTION require_sandbox_billing_account()")
    op.execute("DROP TRIGGER credit_account_kind_immutable ON credit_accounts")
    op.execute("DROP FUNCTION prevent_credit_kind_mutation()")
    op.drop_constraint("ck_credit_account_kind", "credit_accounts", type_="check")
    op.drop_column("credit_accounts", "account_kind")
