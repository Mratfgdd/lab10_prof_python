"""Правила перевірки даних студента."""

import pytest

from student_manager.exceptions import StudentValidationError
from student_manager.validation import (
    clean_email,
    clean_grade,
    clean_group_name,
    clean_name,
)


@pytest.mark.parametrize("grade", [0, 0.0, 100, 100.0, 73.456, 1])
def test_grade_inside_the_scale_is_accepted(grade: float) -> None:
    assert clean_grade(grade) == pytest.approx(float(grade))


@pytest.mark.parametrize(
    "grade",
    [
        -0.01,
        100.01,
        -1,
        101,
        float("nan"),
        float("inf"),
        "90",
        None,
        True,
        [90],
    ],
    ids=[
        "below",
        "above",
        "-1",
        "101",
        "nan",
        "inf",
        "string",
        "none",
        "bool",
        "list",
    ],
)
def test_grade_outside_the_scale_or_not_a_number_is_rejected(
    grade: object,
) -> None:
    with pytest.raises(StudentValidationError, match="середній бал"):
        clean_grade(grade)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Олена", "Олена"), ("  Олена  ", "Олена"), ("О", "О")],
)
def test_name_is_stripped(raw: str, expected: str) -> None:
    assert clean_name(raw, "ім'я") == expected


@pytest.mark.parametrize("raw", ["", "   ", None, 5, "х" * 101])
def test_blank_non_string_or_too_long_name_is_rejected(raw: object) -> None:
    with pytest.raises(StudentValidationError, match="ім'я"):
        clean_name(raw, "ім'я")


@pytest.mark.parametrize(
    "name", ["PI-21", "ФЕП-31", "KN-99", "ABCDE-01", " PI-21 "]
)
def test_valid_group_names(name: str) -> None:
    assert clean_group_name(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    [
        "pi-21",
        "P-21",
        "PI21",
        "PI-2",
        "PI-211",
        "ABCDEF-01",
        "PI-٢١",
        "",
        None,
    ],
    ids=[
        "lower",
        "short",
        "no-dash",
        "one-digit",
        "three-digits",
        "long",
        "arabic-digits",
        "empty",
        "none",
    ],
)
def test_invalid_group_names(name: object) -> None:
    with pytest.raises(StudentValidationError):
        clean_group_name(name)


def test_email_is_lowercased_and_stripped() -> None:
    assert clean_email("  Olena.K@Example.COM ") == "olena.k@example.com"


def test_missing_email_is_allowed() -> None:
    assert clean_email(None) is None


@pytest.mark.parametrize(
    "email", ["", "plain", "a@b", "@b.c", "a@.c", "a b@c.d", 5]
)
def test_invalid_email_is_rejected(email: object) -> None:
    with pytest.raises(StudentValidationError, match="електронної пошти"):
        clean_email(email)
