"""Адреса БД і перевірка схеми."""

from pathlib import Path

import pytest
from support import SetEnv

from student_manager.database import (
    database_url,
    ensure_schema,
    make_engine,
    migrate,
)
from student_manager.exceptions import SchemaMissingError


def test_database_url_defaults_to_a_local_file() -> None:
    assert database_url() == "sqlite:///students.db"


def test_database_url_can_come_from_the_environment(set_env: SetEnv) -> None:
    set_env(database_url="sqlite:///elsewhere.db")
    assert database_url() == "sqlite:///elsewhere.db"


def test_migrate_creates_missing_directory_and_schema(tmp_path: Path) -> None:
    target = tmp_path / "data" / "nested" / "students.db"
    migrate(f"sqlite:///{target}")
    engine = make_engine(f"sqlite:///{target}")
    try:
        ensure_schema(engine)
    finally:
        engine.dispose()


def test_migrate_twice_is_harmless(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'again.db'}"
    migrate(url)
    migrate(url)


def test_migrate_accepts_percent_signs_in_the_url(tmp_path: Path) -> None:
    migrate(f"sqlite:///{tmp_path / 'a%b.db'}")
    assert (tmp_path / "a%b.db").exists()


def test_ensure_schema_requires_migrations_to_be_applied() -> None:
    engine = make_engine("sqlite://")
    try:
        with pytest.raises(SchemaMissingError, match="alembic upgrade head"):
            ensure_schema(engine)
    finally:
        engine.dispose()
