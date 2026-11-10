"""Транзакції: commit, rollback, ізоляція."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from support import Query

from student_manager.exceptions import (
    GroupNotFoundError,
    StudentNotFoundError,
    StudentValidationError,
)
from student_manager.models import Group
from student_manager.services import StudentService, transfer_students


def group_of_object(service: StudentService, name: str) -> Group:
    group = service.groups.get_by_name(name)
    assert group is not None
    return group


def group_id(service: StudentService, name: str) -> int:
    return group_of_object(service, name).id


def test_transfer_moves_every_student_and_commits(
    school: StudentService, session: Session, group_of: Callable[[int], str]
) -> None:
    moved = transfer_students(session, [1, 2], group_id(school, "PI-23"))
    assert moved == 2
    assert [group_of(1), group_of(2), group_of(3), group_of(4)] == [
        "PI-23",
        "PI-23",
        "PI-22",
        "PI-22",
    ]


def test_transfer_updates_both_sides_of_the_relationship(
    school: StudentService, session: Session
) -> None:
    target = group_of_object(school, "PI-23")
    transfer_students(session, [1], target.id)
    assert [s.id for s in target.students] == [1]
    assert school.get_student(1).group is target


def test_transfer_ignores_repeated_ids(
    school: StudentService, session: Session
) -> None:
    assert (
        transfer_students(session, [1, 1, 2, 2, 1], group_id(school, "PI-23"))
        == 2
    )


def test_missing_student_rolls_back_the_whole_transfer(
    school: StudentService, session: Session, group_of: Callable[[int], str]
) -> None:
    with pytest.raises(StudentNotFoundError, match="id=999999"):
        transfer_students(session, [1, 2, 999999], group_id(school, "PI-23"))
    assert [group_of(1), group_of(2)] == ["PI-21", "PI-21"]


def test_missing_student_is_also_a_value_error(
    school: StudentService, session: Session
) -> None:
    with pytest.raises(ValueError, match="не знайдено"):
        transfer_students(session, [999999], group_id(school, "PI-23"))


def test_unknown_target_group_changes_nothing(
    school: StudentService, session: Session, group_of: Callable[[int], str]
) -> None:
    with pytest.raises(GroupNotFoundError):
        transfer_students(session, [1, 2], 424242)
    assert group_of(1) == "PI-21"


def test_empty_transfer_is_rejected(
    school: StudentService, session: Session
) -> None:
    with pytest.raises(StudentValidationError, match="порожній"):
        transfer_students(session, [], group_id(school, "PI-23"))


def test_session_stays_usable_after_a_failed_transfer(
    school: StudentService, session: Session, group_of: Callable[[int], str]
) -> None:
    with pytest.raises(StudentNotFoundError):
        transfer_students(session, [1, 999], group_id(school, "PI-23"))
    assert school.get_student(1).group.name == "PI-21"
    transfer_students(session, [1], group_id(school, "PI-23"))
    assert group_of(1) == "PI-23"


def test_database_failure_in_the_middle_rolls_back_updates_already_sent(
    school: StudentService,
    session: Session,
    group_of: Callable[[int], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = group_id(school, "PI-23")
    real_flush = session.flush
    calls: list[int] = []

    def failing_second_flush(*args: Any, **kwargs: Any) -> None:
        calls.append(1)
        if len(calls) == 2:
            raise OperationalError(
                "UPDATE students", {}, Exception("disk I/O error")
            )
        real_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", failing_second_flush)
    with pytest.raises(OperationalError):
        transfer_students(session, [1, 2, 3], target)
    assert len(calls) == 2
    assert [group_of(1), group_of(2), group_of(3)] == [
        "PI-21",
        "PI-21",
        "PI-22",
    ]


def test_uncommitted_transfer_is_invisible_to_another_connection(
    school: StudentService,
    session: Session,
    group_of: Callable[[int], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = group_id(school, "PI-23")
    real_flush = session.flush
    seen_by_other_connection: list[str] = []

    def spying_flush(*args: Any, **kwargs: Any) -> None:
        real_flush(*args, **kwargs)
        seen_by_other_connection.append(group_of(1))

    monkeypatch.setattr(session, "flush", spying_flush)
    transfer_students(session, [1], target)
    assert seen_by_other_connection == ["PI-21"]
    assert group_of(1) == "PI-23"


def test_service_wrapper_resolves_group_by_name(
    school: StudentService, group_of: Callable[[int], str]
) -> None:
    assert school.transfer_students([3, 4], "PI-21") == 2
    assert [group_of(3), group_of(4)] == ["PI-21", "PI-21"]


def test_service_wrapper_rejects_unknown_group_name(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(GroupNotFoundError):
        school.transfer_students([1], "PI-99")
    assert query("SELECT count(*) FROM students WHERE group_id = 1") == [(2,)]


def test_failed_operation_does_not_leave_a_half_added_student(
    school: StudentService, query: Query
) -> None:
    with pytest.raises(StudentValidationError):
        school.add_student("Софія", "Гнатюк", "PI-23", 120.0)
    with pytest.raises(GroupNotFoundError):
        school.add_student("Софія", "Гнатюк", "PI-77", 90.0)
    assert query("SELECT count(*) FROM students") == [(4,)]
