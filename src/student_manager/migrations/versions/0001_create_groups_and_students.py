"""Створення таблиць groups і students."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Створює таблиці й індекси."""
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name=op.f("ck_groups_name_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("name", name=op.f("uq_groups_name")),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("average_grade", sa.Float(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "average_grade >= 0 AND average_grade <= 100",
            name=op.f("ck_students_grade_in_range"),
        ),
        sa.CheckConstraint(
            "length(trim(first_name)) > 0 AND length(trim(last_name)) > 0",
            name=op.f("ck_students_names_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_students_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_students")),
    )
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_students_group_id"), ["group_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_students_last_name"), ["last_name"], unique=False
        )


def downgrade() -> None:
    """Видаляє таблиці й індекси."""
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_students_last_name"))
        batch_op.drop_index(batch_op.f("ix_students_group_id"))

    op.drop_table("students")
    op.drop_table("groups")
