"""Методи сервісу, потрібні для REST API."""

import sqlite3
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from support import Query

from student_manager.exceptions import (
    DuplicateEmailError,
    GroupNotFoundError,
    StudentNotFoundError,
    StudentValidationError,
)
from student_manager.services import StudentService


def group_id(service: StudentService, name: str) -> int:
    group = service.groups.get_by_name(name)
    assert group is not None
    return group.id


def test_create_student_by_group_id_is_committed(
    school: StudentService, query: Query
) -> None:
    student = school.create_student(
        "Софія", "Гнатюк", group_id(school, "PI-23"), 88.0
    )
    assert query(
        "SELECT last_name, group_id FROM students WHERE id = ?", student.id
    ) == [("Гнатюк", group_id(school, "PI-23"))]


def test_create_student_in_unknown_group_stores_nothing(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(GroupNotFoundError, match="id=999"):
        school.create_student("Софія", "Гнатюк", 999, 88.0)
    assert query("SELECT count(*) FROM students") == [(4,)]


def test_create_student_with_duplicate_email_is_rolled_back(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(DuplicateEmailError):
        school.create_student(
            "Інша",
            "Особа",
            group_id(school, "PI-22"),
            70.0,
            "olena@example.com",
        )
    assert query("SELECT count(*) FROM students") == [(4,)]


def test_update_student_changes_several_fields_in_one_transaction(
    school: StudentService, query: Query
) -> None:
    target = group_id(school, "PI-23")
    school.update_student(
        2,
        {
            "first_name": "Андрій-Марко",
            "average_grade": 85.5,
            "group_id": target,
        },
    )
    assert query(
        "SELECT first_name, average_grade, group_id FROM students WHERE id = 2"
    ) == [("Андрій-Марко", 85.5, target)]


def test_update_student_keeps_everything_when_one_field_is_invalid(
    school: StudentService, query: Query
) -> None:
    before = query(
        "SELECT first_name, average_grade, group_id FROM students WHERE id = 2"
    )
    with pytest.raises(StudentValidationError, match="середній бал"):
        school.update_student(
            2, {"first_name": "Нове", "average_grade": 140.0}
        )
    assert (
        query(
            "SELECT first_name, average_grade, group_id FROM students "
            "WHERE id = 2"
        )
        == before
    )


def test_update_student_with_unknown_group_keeps_other_changes_out(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(GroupNotFoundError):
        school.update_student(2, {"average_grade": 10.0, "group_id": 999})
    assert query("SELECT average_grade FROM students WHERE id = 2") == [
        (80.0,)
    ]


def test_update_student_email_can_be_set_and_cleared(
    school: StudentService, query: Query
) -> None:
    school.update_student(2, {"email": "Andrii@Example.com"})
    assert query("SELECT email FROM students WHERE id = 2") == [
        ("andrii@example.com",)
    ]
    school.update_student(2, {"email": None})
    assert query("SELECT email FROM students WHERE id = 2") == [(None,)]


def test_update_student_duplicate_email_is_rejected(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(DuplicateEmailError):
        school.update_student(2, {"email": "olena@example.com"})
    assert query("SELECT email FROM students WHERE id = 2") == [(None,)]


def test_update_student_rejects_unknown_fields_and_missing_students(
    school: StudentService,
) -> None:
    with pytest.raises(StudentValidationError, match="id"):
        school.update_student(2, {"id": 77})
    with pytest.raises(StudentNotFoundError):
        school.update_student(999, {"average_grade": 50.0})


def test_students_of_group_and_unknown_group(school: StudentService) -> None:
    members = school.students_of_group(group_id(school, "PI-22"))
    assert [s.last_name for s in members] == ["Бондар", "Гриценко"]
    assert school.students_of_group(group_id(school, "PI-23")) == []
    with pytest.raises(GroupNotFoundError):
        school.students_of_group(999)


def test_group_statistics_of_one_group(school: StudentService) -> None:
    stats = school.group_statistics(group_id(school, "PI-21"))
    assert (stats.name, stats.students, stats.best, stats.worst) == (
        "PI-21",
        2,
        95.0,
        80.0,
    )
    assert stats.average == pytest.approx(87.5)


def test_group_statistics_of_empty_and_unknown_group(
    school: StudentService,
) -> None:
    empty = school.group_statistics(group_id(school, "PI-23"))
    assert (empty.students, empty.average) == (0, None)
    with pytest.raises(GroupNotFoundError):
        school.group_statistics(999)


def test_get_group_returns_group_or_raises(school: StudentService) -> None:
    assert school.get_group(group_id(school, "PI-21")).name == "PI-21"
    with pytest.raises(GroupNotFoundError):
        school.get_group(999)


def test_list_students_by_group_id_last_name_and_grade_range(
    school: StudentService,
) -> None:
    pi21 = group_id(school, "PI-21")
    assert [s.last_name for s in school.list_students(group_id=pi21)] == [
        "Коваленко",
        "Мельник",
    ]
    assert [s.id for s in school.list_students(last_name_prefix="Бондар")] == [
        3
    ]
    in_range = school.list_students(
        min_grade=55, max_grade=95, order_by="average_grade"
    )
    assert [s.last_name for s in in_range] == [
        "Гриценко",
        "Мельник",
        "Коваленко",
    ]


def test_list_students_rejects_inverted_range_and_unknown_group(
    school: StudentService,
) -> None:
    with pytest.raises(StudentValidationError, match="min_grade"):
        school.list_students(min_grade=90, max_grade=10)
    with pytest.raises(GroupNotFoundError):
        school.list_students(group_id=999)


def raise_integrity_error(*_args: Any, **_kwargs: Any) -> None:
    raise IntegrityError(
        "INSERT",
        {},
        Exception("CHECK constraint failed: ck_students_something"),
    )


def test_unrelated_integrity_error_is_not_reported_as_duplicate_email(
    school: StudentService, monkeypatch: pytest.MonkeyPatch, query: Query
) -> None:
    monkeypatch.setattr(school.students, "add", raise_integrity_error)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        school.create_student(
            "Софія", "Гнатюк", group_id(school, "PI-23"), 88.0
        )
    assert query("SELECT count(*) FROM students") == [(4,)]


def test_unrelated_integrity_error_while_updating_is_propagated(
    school: StudentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(school.session, "flush", raise_integrity_error)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        school.update_student(2, {"average_grade": 70.0})


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("Мел", ["Мельник"]),
        ("мел", ["Мельник"]),
        ("МЕЛЬНИК", ["Мельник"]),
        ("  гри ", ["Гриценко"]),
        ("к", ["Коваленко"]),
        ("", ["Бондар", "Гриценко", "Коваленко", "Мельник"]),
        ("Ніхто", []),
        ("%", []),
        ("_ельник", []),
    ],
    ids=[
        "exact-case",
        "lower",
        "upper",
        "spaces",
        "one-letter",
        "empty",
        "unknown",
        "percent",
        "underscore",
    ],
)
def test_last_name_prefix_ignores_case_for_cyrillic_and_escapes_wildcards(
    school: StudentService, prefix: str, expected: list[str]
) -> None:
    found = school.list_students(last_name_prefix=prefix)
    assert [s.last_name for s in found] == expected
    assert school.count_students(last_name_prefix=prefix) == len(expected)


def test_count_students_ignores_pagination_and_follows_filters(
    school: StudentService,
) -> None:
    pi22 = group_id(school, "PI-22")
    assert len(school.list_students(limit=1)) == 1
    assert school.count_students() == 4
    assert school.count_students(group_id=pi22) == 2
    assert school.count_students(group_name="PI-21", min_grade=90) == 1
    assert school.count_students(min_grade=60, max_grade=95) == 2


def test_count_students_validates_group_and_range(
    school: StudentService,
) -> None:
    with pytest.raises(GroupNotFoundError):
        school.count_students(group_id=999)
    with pytest.raises(StudentValidationError, match="min_grade"):
        school.count_students(min_grade=90, max_grade=10)


def test_sqlite_casefold_function_handles_unicode_unlike_builtin_lower(
    school: StudentService, query: Query
) -> None:
    row = school.session.execute(
        text("SELECT lower('ГРИЦЕНКО'), casefold('ГРИЦЕНКО'), casefold(NULL)")
    ).one()
    assert tuple(row) == ("ГРИЦЕНКО", "гриценко", None)
    assert (
        school.session.execute(text("SELECT casefold('ЇЖАК')")).scalar()
        == "їжак"
    )
    with pytest.raises(
        sqlite3.OperationalError, match="no such function: casefold"
    ):
        query("SELECT casefold('ЇЖАК')")
