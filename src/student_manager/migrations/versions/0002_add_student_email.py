"""Додає поле email до таблиці students."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Додає колонку email з обмеженнями UNIQUE і CHECK."""
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("email", sa.String(length=255), nullable=True)
        )
        batch_op.create_unique_constraint(
            batch_op.f("uq_students_email"), ["email"]
        )
        batch_op.create_check_constraint(
            op.f("ck_students_email_format"),
            "email IS NULL OR email LIKE '%_@_%._%'",
        )


def downgrade() -> None:
    """Видаляє колонку email та її обмеження."""
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("ck_students_email_format"), type_="check"
        )
        batch_op.drop_constraint(
            batch_op.f("uq_students_email"), type_="unique"
        )
        batch_op.drop_column("email")
