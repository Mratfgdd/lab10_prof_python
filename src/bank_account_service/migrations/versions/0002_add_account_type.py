"""add account type

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05 17:23:15.708660

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "account_type", sa.String(length=10), server_default="current", nullable=False
            )
        )
        batch_op.create_check_constraint(
            op.f("ck_accounts_known_type"), "account_type IN ('current', 'savings')"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_accounts_known_type"), type_="check")
        batch_op.drop_column("account_type")
