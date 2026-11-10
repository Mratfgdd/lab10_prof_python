"""StudentService: бізнес-логіка."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from support import Query

from student_manager.exceptions import (
    DuplicateEmailError,
    DuplicateGroupError,
    GroupNotEmptyError,
    GroupNotFoundError,
    StudentNotFoundError,
    StudentValidationError,
)
from student_manager.services import StudentService


def test_create_group_is_committed(
    service: StudentService, query: Query
) -> None:
    group = service.create_group("PI-21")
    assert group.id is not None
    assert query("SELECT name FROM groups") == [("PI-21",)]


def test_duplicate_group_raises_domain_error_and_keeps_one_row(
    service: StudentService, query: Query
) -> None:
    service.create_group("PI-21")
    with pytest.raises(DuplicateGroupError, match="PI-21"):
        service.create_group("PI-21")
    assert query("SELECT count(*) FROM groups") == [(1,)]


def test_invalid_group_name_is_rejected(service: StudentService) -> None:
    with pytest.raises(StudentValidationError):
        service.create_group("group one")


def test_add_student_stores_row_with_group_link(
    school: StudentService, query: Query
) -> None:
    student = school.add_student(
        "Софія", "Гнатюк", "PI-23", 88.0, " Sofia@Example.com "
    )
    assert query(
        "SELECT first_name, average_grade, email FROM students WHERE id = ?",
        student.id,
    ) == [("Софія", 88.0, "sofia@example.com")]


def test_add_student_to_unknown_group_stores_nothing(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(GroupNotFoundError, match="PI-99"):
        school.add_student("Софія", "Гнатюк", "PI-99", 88.0)
    assert query("SELECT count(*) FROM students") == [(4,)]


def test_add_student_with_duplicate_email_is_rolled_back(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(DuplicateEmailError, match="olena@example.com"):
        school.add_student("Інша", "Особа", "PI-22", 70.0, "OLENA@example.com")
    assert query("SELECT count(*) FROM students") == [(4,)]
    school.add_student("Інша", "Особа", "PI-22", 70.0)
    assert query("SELECT count(*) FROM students") == [(5,)]


@pytest.mark.parametrize("grade", [-0.01, 100.01, float("nan"), "90"])
def test_add_student_with_invalid_grade_is_rejected(
    school: StudentService, query: Query, grade: Any
) -> None:
    with pytest.raises(StudentValidationError):
        school.add_student("Софія", "Гнатюк", "PI-23", grade)
    assert query("SELECT count(*) FROM students") == [(4,)]


@pytest.mark.parametrize("grade", [0, 100])
def test_add_student_accepts_boundary_grades(
    school: StudentService, grade: float
) -> None:
    assert (
        school.add_student("Софія", "Гнатюк", "PI-23", grade).average_grade
        == grade
    )


def test_get_student_returns_existing_and_raises_for_unknown(
    school: StudentService,
) -> None:
    assert school.get_student(3).last_name == "Бондар"
    with pytest.raises(StudentNotFoundError, match="id=999"):
        school.get_student(999)


def test_find_by_last_name(school: StudentService) -> None:
    assert [s.first_name for s in school.find_by_last_name("Мельник")] == [
        "Андрій"
    ]
    assert school.find_by_last_name("Ніхто") == []


def test_filter_by_group(school: StudentService) -> None:
    assert [s.last_name for s in school.filter_by_group("PI-21")] == [
        "Коваленко",
        "Мельник",
    ]
    assert school.filter_by_group("PI-23") == []


def test_filter_by_unknown_group_raises(school: StudentService) -> None:
    with pytest.raises(GroupNotFoundError):
        school.filter_by_group("PI-99")


def test_list_students_applies_filters_sorting_and_pages(
    school: StudentService,
) -> None:
    top = school.list_students(
        min_grade=60, order_by="average_grade", descending=True, limit=2
    )
    assert [s.last_name for s in top] == ["Бондар", "Коваленко"]
    in_group = school.list_students(
        group_name="PI-22", order_by="average_grade"
    )
    assert [s.last_name for s in in_group] == ["Гриценко", "Бондар"]


def test_group_average_is_computed_by_sql(school: StudentService) -> None:
    group = school.groups.get_by_name("PI-21")
    assert group is not None
    assert school.get_group_average(group.id) == pytest.approx(87.5)
    assert school.get_group_average_by_name("PI-22") == pytest.approx(77.25)


def test_group_average_of_empty_group_is_zero(school: StudentService) -> None:
    assert school.get_group_average_by_name("PI-23") == 0.0


def test_group_average_changes_after_grade_update(
    school: StudentService,
) -> None:
    school.update_grade(2, 100.0)
    assert school.get_group_average_by_name("PI-21") == pytest.approx(97.5)


def test_best_student(school: StudentService) -> None:
    best = school.get_best_student()
    assert best is not None
    assert (best.last_name, best.average_grade) == ("Бондар", 99.5)


def test_best_student_of_empty_database_is_none(
    service: StudentService,
) -> None:
    assert service.get_best_student() is None


def test_group_report_contains_empty_groups(school: StudentService) -> None:
    report = {item.name: item for item in school.group_report()}
    assert report["PI-21"].students == 2
    assert report["PI-21"].best == 95.0
    assert report["PI-23"].students == 0
    assert report["PI-23"].average is None


def test_update_grade_is_persisted(
    school: StudentService, query: Query
) -> None:
    updated = school.update_grade(4, 72.5)
    assert updated.average_grade == pytest.approx(72.5)
    assert query("SELECT average_grade FROM students WHERE id = 4") == [
        (72.5,)
    ]


def test_update_grade_of_unknown_student_raises(
    school: StudentService,
) -> None:
    with pytest.raises(StudentNotFoundError):
        school.update_grade(999, 70.0)


@pytest.mark.parametrize("grade", [-5, 101, float("nan")])
def test_invalid_grade_update_keeps_stored_value(
    school: StudentService, query: Query, grade: float
) -> None:
    with pytest.raises(StudentValidationError):
        school.update_grade(4, grade)
    assert query("SELECT average_grade FROM students WHERE id = 4") == [
        (55.0,)
    ]


def test_set_email_and_clear_it(school: StudentService, query: Query) -> None:
    school.set_email(2, "Andrii@Example.com")
    assert query("SELECT email FROM students WHERE id = 2") == [
        ("andrii@example.com",)
    ]
    school.set_email(2, None)
    assert query("SELECT email FROM students WHERE id = 2") == [(None,)]


def test_set_duplicate_email_is_rejected_and_rolled_back(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(DuplicateEmailError):
        school.set_email(2, "olena@example.com")
    assert query("SELECT email FROM students WHERE id = 2") == [(None,)]


def test_set_invalid_email_or_unknown_student(school: StudentService) -> None:
    with pytest.raises(StudentValidationError):
        school.set_email(2, "broken")
    with pytest.raises(StudentNotFoundError):
        school.set_email(999, "a@example.com")


def test_delete_student(school: StudentService, query: Query) -> None:
    school.delete_student(1)
    assert query("SELECT count(*) FROM students WHERE id = 1") == [(0,)]
    assert query("SELECT count(*) FROM students") == [(3,)]


def test_delete_unknown_student_raises(school: StudentService) -> None:
    with pytest.raises(StudentNotFoundError):
        school.delete_student(999)


def test_delete_empty_group(school: StudentService, query: Query) -> None:
    assert school.delete_group("PI-23") == 0
    assert query("SELECT name FROM groups ORDER BY name") == [
        ("PI-21",),
        ("PI-22",),
    ]


def test_delete_group_with_students_is_refused_without_force(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(GroupNotEmptyError, match="2"):
        school.delete_group("PI-21")
    assert query("SELECT count(*) FROM students") == [(4,)]
    assert query("SELECT count(*) FROM groups") == [(3,)]


def test_forced_group_deletion_cascades_to_students(
    school: StudentService, query: Query, group_of: Callable[[int], str]
) -> None:
    assert school.delete_group("PI-21", force=True) == 2
    assert query("SELECT count(*) FROM students") == [(2,)]
    assert group_of(3) == "PI-22"


def test_delete_unknown_group_raises(school: StudentService) -> None:
    with pytest.raises(GroupNotFoundError):
        school.delete_group("PI-99")


def raise_integrity_error(*_args: Any, **_kwargs: Any) -> None:
    raise IntegrityError(
        "INSERT",
        {},
        Exception("CHECK constraint failed: ck_students_something"),
    )


def test_unrelated_integrity_error_is_not_reported_as_duplicate_group(
    service: StudentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.groups, "add", raise_integrity_error)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        service.create_group("PI-21")


def test_unrelated_integrity_error_is_not_reported_as_duplicate_email(
    school: StudentService, monkeypatch: pytest.MonkeyPatch, query: Query
) -> None:
    monkeypatch.setattr(school.students, "add", raise_integrity_error)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        school.add_student("Софія", "Гнатюк", "PI-23", 88.0)
    assert query("SELECT count(*) FROM students") == [(4,)]


def test_unrelated_integrity_error_while_changing_email_is_propagated(
    school: StudentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(school.session, "flush", raise_integrity_error)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        school.set_email(2, "andrii@example.com")
