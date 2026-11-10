"""Міграції Alembic: upgrade, downgrade, дані."""

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, inspect

from student_manager.database import MIGRATIONS
from student_manager.models import Base

BROKEN_REVISION = """from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("note", sa.String(50)))
    raise RuntimeError("помилка посередині міграції")


def downgrade() -> None:
    pass
"""


def columns(db_path: Path, table: str) -> list[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return [
            column["name"] for column in inspect(engine).get_columns(table)
        ]
    finally:
        engine.dispose()


def fill_revision_0001(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            INSERT INTO groups (id, name) VALUES (1, 'PI-21');
            INSERT INTO students
                (id, first_name, last_name, average_grade, group_id)
                VALUES (1, 'Олена', 'Коваленко', 95.0, 1),
                       (2, 'Андрій', 'Мельник', 80.0, 1);
            """
        )


def test_upgrade_head_creates_schema_identical_to_models(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert context.get_current_revision() == "0002"
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()


def test_first_revision_has_no_email_column(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "0001")
    assert columns(db_path, "students") == [
        "id",
        "first_name",
        "last_name",
        "average_grade",
        "group_id",
    ]


def test_second_revision_adds_nullable_email(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    assert columns(db_path, "students")[-1] == "email"
    engine = create_engine(f"sqlite:///{db_path}")
    email = next(
        c
        for c in inspect(engine).get_columns("students")
        if c["name"] == "email"
    )
    engine.dispose()
    assert email["nullable"] is True


def test_migration_keeps_existing_rows_and_sets_email_to_null(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "0001")
    fill_revision_0001(db_path)
    command.upgrade(alembic_cfg, "head")
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT last_name, average_grade, group_id, email FROM "
            "students "
            "ORDER BY id"
        ).fetchall()
    assert rows == [("Коваленко", 95.0, 1, None), ("Мельник", 80.0, 1, None)]


def test_indexes_and_foreign_key_survive_the_batch_rebuild(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    index_names = {
        index["name"] for index in inspector.get_indexes("students")
    }
    foreign_keys = inspector.get_foreign_keys("students")
    engine.dispose()
    assert {"ix_students_group_id", "ix_students_last_name"} <= index_names
    assert [
        (fk["referred_table"], fk["options"].get("ondelete"))
        for fk in foreign_keys
    ] == [("groups", "CASCADE")]


def test_constraints_added_by_the_migration_work(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    fill_revision_0001(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "UPDATE students SET email = 'a@example.com' WHERE id = 1"
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="UNIQUE constraint failed: students.email",
        ):
            connection.execute(
                "UPDATE students SET email = 'a@example.com' WHERE id = 2"
            )
        with pytest.raises(
            sqlite3.IntegrityError, match="ck_students_email_format"
        ):
            connection.execute(
                "UPDATE students SET email = 'broken' WHERE id = 2"
            )


def test_downgrade_removes_email_and_keeps_students(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    fill_revision_0001(db_path)
    command.downgrade(alembic_cfg, "0001")
    assert "email" not in columns(db_path, "students")
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM students"
        ).fetchone() == (2,)


def test_downgrade_to_base_removes_all_tables(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    engine = create_engine(f"sqlite:///{db_path}")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_upgrade_downgrade_upgrade_returns_to_the_same_schema(
    alembic_cfg: Config, db_path: Path
) -> None:
    command.upgrade(alembic_cfg, "head")
    before = columns(db_path, "students")
    command.downgrade(alembic_cfg, "-1")
    command.upgrade(alembic_cfg, "head")
    assert columns(db_path, "students") == before


def test_offline_mode_prints_first_revision_sql_without_touching_the_db(
    alembic_cfg: Config, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_cfg, "base:0001", sql=True)
    output = capsys.readouterr().out
    assert "CREATE TABLE groups" in output
    assert "CREATE TABLE students" in output
    assert "email" not in output
    assert not db_path.exists()


def test_batch_revision_cannot_be_rendered_offline_on_sqlite(
    alembic_cfg: Config, db_path: Path
) -> None:
    with pytest.raises(
        CommandError, match="requires a live database connection"
    ):
        command.upgrade(alembic_cfg, "0001:0002", sql=True)
    assert not db_path.exists()


def test_failed_migration_leaves_the_schema_untouched(
    alembic_cfg: Config, db_path: Path, tmp_path: Path
) -> None:
    scripts = tmp_path / "migrations"
    shutil.copytree(
        MIGRATIONS,
        scripts,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (scripts / "versions" / "0003_broken.py").write_text(
        BROKEN_REVISION, encoding="utf-8"
    )
    alembic_cfg.set_main_option("script_location", str(scripts))
    command.upgrade(alembic_cfg, "0002")
    with pytest.raises(RuntimeError, match="посередині міграції"):
        command.upgrade(alembic_cfg, "head")
    assert "note" not in columns(db_path, "students")
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0002",)
