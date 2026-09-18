"""add document pipeline idempotency constraints

Revision ID: 20260916_0005
Revises: 20260916_0004
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0005"
down_revision: str | None = "20260916_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_attachment_version_source_url",
        "attachments",
        ["opportunity_version_id", "source_url"],
    )
    op.create_unique_constraint(
        "uq_document_parse_version",
        "document_parses",
        ["attachment_id", "parser_kind", "parser_version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_document_parse_version", "document_parses", type_="unique")
    op.drop_constraint("uq_attachment_version_source_url", "attachments", type_="unique")
