"""Параметризований пошук через DB-API."""

from pathlib import Path

import pytest

from student_manager.dbapi import (
    FIND_BY_GROUP,
    StudentRow,
    find_students_by_group,
)
from student_manager.services import StudentService


def test_search_returns_rows_of_the_group_sorted_by_name(
    school: StudentService, db_path: Path
) -> None:
    rows = find_students_by_group(db_path, "PI-22")
    assert [(r.last_name, r.first_name) for r in rows] == [
        ("Бондар", "Ірина"),
        ("Гриценко", "Тарас"),
    ]
    assert rows[0] == StudentRow(3, "Бондар", "Ірина", "PI-22", 99.5, None)


def test_search_exposes_email_added_by_migration(
    school: StudentService, db_path: Path
) -> None:
    rows = find_students_by_group(db_path, "PI-21")
    assert [r.email for r in rows] == ["olena@example.com", None]


def test_search_of_empty_or_unknown_group_returns_empty_list(
    school: StudentService, db_path: Path
) -> None:
    assert find_students_by_group(db_path, "PI-23") == []
    assert find_students_by_group(db_path, "PI-99") == []


@pytest.mark.parametrize(
    "payload",
    [
        "PI-21' OR '1'='1",
        "PI-21'; DROP TABLE students; --",
        "' UNION SELECT 1,2,3,4,5,6 --",
    ],
    ids=["or-true", "drop-table", "union"],
)
def test_injection_payload_is_treated_as_a_value(
    school: StudentService, db_path: Path, payload: str
) -> None:
    assert find_students_by_group(db_path, payload) == []
    assert len(find_students_by_group(db_path, "PI-21")) == 2


def test_query_text_uses_a_placeholder_not_string_formatting() -> None:
    assert FIND_BY_GROUP.count("?") == 1
    assert "{" not in FIND_BY_GROUP
    assert "%s" not in FIND_BY_GROUP


def test_search_sees_only_committed_data(
    school: StudentService, db_path: Path
) -> None:
    school.add_student("Софія", "Гнатюк", "PI-23", 88.0)
    assert [r.last_name for r in find_students_by_group(db_path, "PI-23")] == [
        "Гнатюк"
    ]


def test_database_path_may_be_a_string(
    school: StudentService, db_path: Path
) -> None:
    assert len(find_students_by_group(str(db_path), "PI-22")) == 2
