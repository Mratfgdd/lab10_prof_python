"""create bank schema

Revision ID: 0001
Revises:
Create Date: 2026-11-05 17:22:54.962529

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.CheckConstraint("length(trim(full_name)) > 0", name=op.f("ck_clients_name_not_blank")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=11), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance_cents", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("balance_cents >= 0", name=op.f("ck_accounts_balance_not_negative")),
        sa.CheckConstraint("length(currency) = 3", name=op.f("ck_accounts_currency_code")),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_accounts_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("number", name=op.f("uq_accounts_number")),
    )
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_accounts_client_id"), ["client_id"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=12), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("balance_after_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "operation IN ('deposit', 'withdraw', 'transfer_in', 'transfer_out')",
            name=op.f("ck_transactions_known_operation"),
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_transactions_amount_positive")),
        sa.CheckConstraint(
            "balance_after_cents >= 0", name=op.f("ck_transactions_balance_after_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_transactions_account_id"), ["account_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transactions_account_id"))

    op.drop_table("transactions")
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_accounts_client_id"))

    op.drop_table("accounts")
    op.drop_table("clients")
