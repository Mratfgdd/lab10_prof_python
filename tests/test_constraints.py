"""Обмеження цілісності на рівні БД."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from support import Query

INSERT_STUDENT = text(
    "INSERT INTO students (first_name, last_name, average_grade, group_id, "
    "email) "
    "VALUES (:first, :last, :grade, :group_id, :email)"
)


def insert_student(engine: Engine, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "first": "Олена",
        "last": "Коваленко",
        "grade": 90.0,
        "group_id": 1,
        "email": None,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(INSERT_STUDENT, values)


@pytest.fixture
def seeded_group(engine: Engine) -> Engine:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO groups (name) VALUES ('PI-21')"))
    return engine


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"grade": 100.1}, "grade_in_range"),
        ({"grade": -0.1}, "grade_in_range"),
        ({"first": "   "}, "names_not_blank"),
        ({"last": ""}, "names_not_blank"),
        ({"email": "no-at-sign"}, "email_format"),
        ({"email": "a@b"}, "email_format"),
    ],
    ids=[
        "grade-high",
        "grade-low",
        "first-blank",
        "last-empty",
        "email-no-at",
        "email-no-dot",
    ],
)
def test_check_constraints_reject_bad_rows_even_without_the_orm(
    seeded_group: Engine, overrides: dict[str, object], constraint: str
) -> None:
    with pytest.raises(
        IntegrityError,
        match=f"CHECK constraint failed: ck_students_{constraint}",
    ):
        insert_student(seeded_group, **overrides)


@pytest.mark.parametrize("grade", [0.0, 100.0])
def test_boundary_grades_are_accepted_by_the_database(
    seeded_group: Engine, grade: float
) -> None:
    insert_student(seeded_group, grade=grade)


def test_group_name_must_not_be_blank(engine: Engine) -> None:
    with pytest.raises(
        IntegrityError,
        match="CHECK constraint failed: ck_groups_name_not_blank",
    ):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO groups (name) VALUES ('  ')"))


def test_group_name_is_unique(seeded_group: Engine) -> None:
    with pytest.raises(
        IntegrityError, match="UNIQUE constraint failed: groups.name"
    ):
        with seeded_group.begin() as connection:
            connection.execute(
                text("INSERT INTO groups (name) VALUES ('PI-21')")
            )


def test_email_is_unique(seeded_group: Engine) -> None:
    insert_student(seeded_group, email="a@example.com")
    with pytest.raises(
        IntegrityError, match="UNIQUE constraint failed: students.email"
    ):
        insert_student(seeded_group, last="Мельник", email="a@example.com")


def test_unique_email_allows_many_students_without_email(
    seeded_group: Engine, query: Query
) -> None:
    for last in ("Коваленко", "Мельник", "Бондар"):
        insert_student(seeded_group, last=last, email=None)
    assert query("SELECT count(*) FROM students WHERE email IS NULL") == [(3,)]


def test_foreign_key_is_enforced_by_the_engine(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        insert_student(engine, group_id=999)


def test_plain_dbapi_connection_ignores_foreign_keys_without_the_pragma(
    engine: Engine, db_path: Path
) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO students (first_name, last_name, average_grade, "
            "group_id) "
            "VALUES ('Олена', 'Коваленко', 90, 999)"
        )
        connection.commit()
        orphans = connection.execute(
            "SELECT count(*) FROM students s LEFT JOIN groups g ON g.id = "
            "s.group_id "
            "WHERE g.id IS NULL"
        ).fetchone()
    assert orphans == (1,)


def test_database_cascades_group_deletion_to_students(
    seeded_group: Engine, query: Query
) -> None:
    insert_student(seeded_group)
    with seeded_group.begin() as connection:
        connection.execute(text("DELETE FROM groups WHERE id = 1"))
    assert query("SELECT count(*) FROM students") == [(0,)]
