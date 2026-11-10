"""ORM-моделі: перевірки, relationship, каскад."""

import pytest
from sqlalchemy.orm import Session
from support import Query

from student_manager.exceptions import StudentValidationError
from student_manager.models import Group, Student


def make_group(session: Session, name: str = "PI-21") -> Group:
    group = Group(name=name)
    session.add(group)
    session.commit()
    return group


def test_student_fields_are_normalized_on_assignment(session: Session) -> None:
    group = make_group(session)
    student = Student(
        first_name="  Олена ",
        last_name="Коваленко  ",
        average_grade=95,
        email=" Olena@Example.com ",
        group=group,
    )
    assert (student.first_name, student.last_name) == ("Олена", "Коваленко")
    assert student.email == "olena@example.com"
    assert student.average_grade == pytest.approx(95.0)
    assert isinstance(student.average_grade, float)


def test_full_name_puts_last_name_first(session: Session) -> None:
    student = Student(
        first_name="Ірина",
        last_name="Бондар",
        average_grade=90,
        group=make_group(session),
    )
    assert student.full_name == "Бондар Ірина"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("first_name", "", "ім'я"),
        ("last_name", "   ", "прізвище"),
        ("average_grade", 100.5, "середній бал"),
        ("average_grade", -1, "середній бал"),
        ("average_grade", "95", "середній бал"),
        ("email", "not-an-email", "електронної пошти"),
    ],
)
def test_invalid_values_are_rejected_before_reaching_the_database(
    session: Session, field: str, value: object, message: str
) -> None:
    fields: dict[str, object] = {
        "first_name": "Олена",
        "last_name": "Коваленко",
        "average_grade": 90.0,
        "group": make_group(session),
    }
    fields[field] = value
    with pytest.raises(StudentValidationError, match=message):
        Student(**fields)


def test_group_name_is_validated(session: Session) -> None:
    with pytest.raises(StudentValidationError, match="назва групи"):
        Group(name="21-PI")


def test_one_to_many_relationship_links_both_sides(session: Session) -> None:
    group = make_group(session)
    first = Student(
        first_name="Олена",
        last_name="Коваленко",
        average_grade=95,
        group=group,
    )
    second = Student(
        first_name="Андрій", last_name="Мельник", average_grade=80, group=group
    )
    session.add_all([first, second])
    session.commit()
    assert group.students == [first, second]
    assert first.group is group
    assert first.group_id == group.id


def test_student_appended_to_group_collection_is_saved(
    session: Session, query: Query
) -> None:
    group = make_group(session)
    group.students.append(
        Student(first_name="Олена", last_name="Коваленко", average_grade=95)
    )
    session.commit()
    assert query("SELECT last_name FROM students") == [("Коваленко",)]


def test_student_removed_from_the_collection_is_deleted_as_orphan(
    session: Session, query: Query
) -> None:
    group = make_group(session)
    student = Student(
        first_name="Олена",
        last_name="Коваленко",
        average_grade=95,
        group=group,
    )
    session.add(student)
    session.commit()
    group.students.remove(student)
    session.commit()
    assert query("SELECT count(*) FROM students") == [(0,)]


def test_deleting_a_group_cascades_to_its_students(
    session: Session, query: Query
) -> None:
    group = make_group(session)
    session.add(
        Student(
            first_name="Олена",
            last_name="Коваленко",
            average_grade=95,
            group=group,
        )
    )
    session.commit()
    session.delete(group)
    session.commit()
    assert query("SELECT count(*) FROM students") == [(0,)]
    assert query("SELECT count(*) FROM groups") == [(0,)]
