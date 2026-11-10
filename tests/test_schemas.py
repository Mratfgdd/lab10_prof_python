"""Pydantic-схеми й правила валідації."""

from typing import Any

import pytest
from pydantic import ValidationError

from student_manager.repositories import GroupStats
from student_manager.schemas import (
    BatchStatisticsIn,
    GroupCreate,
    GroupStatisticsOut,
    StudentCreate,
    StudentUpdate,
    TransferIn,
)

VALID: dict[str, Any] = {
    "first_name": "Олена",
    "last_name": "Коваленко",
    "group_id": 1,
    "average_grade": 91.5,
}


def test_valid_student_is_accepted_and_names_are_stripped() -> None:
    student = StudentCreate(
        **{**VALID, "first_name": "  Олена ", "email": " A@Example.com "}
    )
    assert student.first_name == "Олена"
    assert student.email == "A@Example.com"


def test_email_is_optional() -> None:
    assert StudentCreate(**VALID).email is None


@pytest.mark.parametrize("grade", [0, 100, 0.0, 99.99])
def test_boundary_grades_are_valid(grade: float) -> None:
    assert (
        StudentCreate(**{**VALID, "average_grade": grade}).average_grade
        == grade
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_name", "О"),
        ("first_name", ""),
        ("last_name", "х" * 101),
        ("group_id", 0),
        ("group_id", -1),
        ("group_id", "abc"),
        ("average_grade", -0.01),
        ("average_grade", 100.01),
        ("average_grade", "good"),
        ("email", "no-at"),
        ("email", "a@b"),
    ],
)
def test_invalid_create_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as raised:
        StudentCreate(**{**VALID, field: value})
    assert raised.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "missing", ["first_name", "last_name", "group_id", "average_grade"]
)
def test_required_fields_cannot_be_omitted(missing: str) -> None:
    data = {key: value for key, value in VALID.items() if key != missing}
    with pytest.raises(ValidationError, match="Field required"):
        StudentCreate(**data)


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        StudentCreate(**{**VALID, "nickname": "Оля"})


def test_update_accepts_a_single_field_and_remembers_which_were_set() -> None:
    update = StudentUpdate(average_grade=70)
    assert update.model_dump(exclude_unset=True) == {"average_grade": 70}


def test_update_allows_clearing_the_email() -> None:
    assert StudentUpdate(email=None).model_dump(exclude_unset=True) == {
        "email": None
    }


def test_empty_update_is_rejected() -> None:
    with pytest.raises(ValidationError, match="хоча б одне поле"):
        StudentUpdate()


@pytest.mark.parametrize(
    "field", ["first_name", "last_name", "group_id", "average_grade"]
)
def test_update_cannot_set_required_fields_to_null(field: str) -> None:
    with pytest.raises(ValidationError, match="не може бути null"):
        StudentUpdate(**{field: None})


@pytest.mark.parametrize("name", ["PI-21", " ФЕП-31 ", "KN-99"])
def test_valid_group_names(name: str) -> None:
    assert GroupCreate(name=name).name == name.strip()


@pytest.mark.parametrize(
    "name", ["pi-21", "PI21", "PI-2", "PI-٢١", "", "PI-21\nX"]
)
def test_invalid_group_names(name: str) -> None:
    with pytest.raises(ValidationError):
        GroupCreate(name=name)


@pytest.mark.parametrize("ids", [[], [0], [-1], list(range(1, 502))])
def test_transfer_requires_between_one_and_five_hundred_positive_ids(
    ids: list[int],
) -> None:
    with pytest.raises(ValidationError):
        TransferIn(student_ids=ids)


@pytest.mark.parametrize("ids", [[], [0], list(range(1, 52))])
def test_batch_requires_between_one_and_fifty_positive_ids(
    ids: list[int],
) -> None:
    with pytest.raises(ValidationError):
        BatchStatisticsIn(group_ids=ids)


def test_statistics_schema_rounds_average_and_keeps_none_for_empty() -> None:
    filled = GroupStatisticsOut.from_stats(
        GroupStats(1, "PI-21", 3, 86.16666, 95.0, 78.0)
    )
    empty = GroupStatisticsOut.from_stats(
        GroupStats(2, "PI-23", 0, None, None, None)
    )
    assert (filled.average_grade, filled.students_count) == (86.17, 3)
    assert (empty.average_grade, empty.best_grade, empty.students_count) == (
        None,
        None,
        0,
    )
