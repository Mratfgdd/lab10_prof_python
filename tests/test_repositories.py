"""Репозиторії: StudentRepository і GroupRepository."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from support import Query

from student_manager.models import Group, Student
from student_manager.repositories import (
    GroupRepository,
    GroupStats,
    StudentRepository,
)


@pytest.fixture
def groups_by_name(session: Session) -> dict[str, Group]:
    repository = GroupRepository(session)
    return {
        name: repository.create(name) for name in ("PI-21", "PI-22", "PI-23")
    }


@pytest.fixture
def students(
    session: Session, groups_by_name: dict[str, Group]
) -> StudentRepository:
    repository = StudentRepository(session)
    rows = [
        ("Олена", "Коваленко", 95.0, "PI-21"),
        ("Андрій", "Мельник", 80.0, "PI-21"),
        ("Ірина", "Бондар", 99.5, "PI-22"),
        ("Тарас", "Гриценко", 55.0, "PI-22"),
        ("Марта", "Мельник", 80.0, "PI-22"),
    ]
    for first, last, grade, group in rows:
        repository.add(
            Student(
                first_name=first,
                last_name=last,
                average_grade=grade,
                group=groups_by_name[group],
            )
        )
    return repository


def test_add_assigns_id_and_stores_the_row(
    students: StudentRepository, session: Session, query: Query
) -> None:
    session.commit()
    assert query("SELECT count(*) FROM students") == [(5,)]
    assert query(
        "SELECT first_name, last_name, average_grade FROM students WHERE "
        "id = 1"
    ) == [("Олена", "Коваленко", 95.0)]


def test_get_by_id_returns_the_student(students: StudentRepository) -> None:
    loaded = students.get_by_id(3)
    assert loaded is not None
    assert loaded.last_name == "Бондар"
    assert loaded.group.name == "PI-22"


def test_get_by_unknown_id_returns_none(students: StudentRepository) -> None:
    assert students.get_by_id(999) is None


def test_get_all_is_ordered_by_id(students: StudentRepository) -> None:
    assert [s.id for s in students.get_all()] == [1, 2, 3, 4, 5]


def test_get_all_supports_pagination(students: StudentRepository) -> None:
    assert [s.id for s in students.get_all(limit=2)] == [1, 2]
    assert [s.id for s in students.get_all(limit=2, offset=2)] == [3, 4]
    assert [s.id for s in students.get_all(limit=10, offset=4)] == [5]


def test_count(students: StudentRepository) -> None:
    assert students.count() == 5


def test_update_grade_changes_only_the_grade(
    students: StudentRepository, session: Session, query: Query
) -> None:
    updated = students.update_grade(4, 61.5)
    session.commit()
    assert updated is not None
    assert updated.average_grade == pytest.approx(61.5)
    assert query(
        "SELECT average_grade, last_name FROM students WHERE id = 4"
    ) == [(61.5, "Гриценко")]


def test_update_grade_of_unknown_student_returns_none(
    students: StudentRepository,
) -> None:
    assert students.update_grade(999, 70.0) is None


def test_delete_removes_the_student(
    students: StudentRepository, session: Session, query: Query
) -> None:
    assert students.delete(2) is True
    session.commit()
    assert query("SELECT count(*) FROM students WHERE id = 2") == [(0,)]
    assert students.count() == 4


def test_delete_of_unknown_student_returns_false(
    students: StudentRepository,
) -> None:
    assert students.delete(999) is False


def test_find_by_last_name_returns_all_namesakes_ordered_by_first_name(
    students: StudentRepository,
) -> None:
    assert [
        (s.first_name, s.group.name)
        for s in students.find_by_last_name("Мельник")
    ] == [
        ("Андрій", "PI-21"),
        ("Марта", "PI-22"),
    ]


def test_find_by_last_name_ignores_surrounding_spaces(
    students: StudentRepository,
) -> None:
    assert [s.id for s in students.find_by_last_name("  Бондар ")] == [3]


def test_find_by_last_name_is_case_sensitive(
    students: StudentRepository,
) -> None:
    assert students.find_by_last_name("бондар") == []


def test_find_by_unknown_last_name_returns_empty_list(
    students: StudentRepository,
) -> None:
    assert students.find_by_last_name("Ніхто") == []


def test_find_by_group_returns_group_members_sorted_by_name(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    found = students.find_by_group(groups_by_name["PI-22"].id)
    assert [s.last_name for s in found] == ["Бондар", "Гриценко", "Мельник"]


def test_find_by_group_of_empty_group_is_empty(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    assert students.find_by_group(groups_by_name["PI-23"].id) == []


def test_filter_by_group_name_joins_through_the_groups_table(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    by_name = students.filter_by_group("PI-21")
    assert by_name == students.find_by_group(groups_by_name["PI-21"].id)
    assert students.filter_by_group("PI-99") == []


def test_search_without_filters_returns_everyone_sorted_by_last_name(
    students: StudentRepository,
) -> None:
    assert [s.last_name for s in students.search()] == [
        "Бондар",
        "Гриценко",
        "Коваленко",
        "Мельник",
        "Мельник",
    ]


def test_search_combines_group_and_grade_filters(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    found = students.search(
        group_id=groups_by_name["PI-22"].id, min_grade=60, max_grade=99
    )
    assert [s.last_name for s in found] == ["Мельник"]


def test_search_grade_bounds_are_inclusive(
    students: StudentRepository,
) -> None:
    found = students.search(
        min_grade=80.0, max_grade=95.0, order_by="average_grade"
    )
    assert [s.average_grade for s in found] == [80.0, 80.0, 95.0]


def test_search_sorts_by_grade_descending_with_id_as_tie_breaker(
    students: StudentRepository,
) -> None:
    ordered = students.search(order_by="average_grade", descending=True)
    assert [s.id for s in ordered] == [3, 1, 2, 5, 4]


def test_search_paginates_after_sorting(students: StudentRepository) -> None:
    page = students.search(
        order_by="average_grade", descending=True, limit=2, offset=1
    )
    assert [s.id for s in page] == [1, 2]


def test_best_returns_the_highest_average(students: StudentRepository) -> None:
    best = students.best()
    assert best is not None
    assert best.last_name == "Бондар"


def test_best_breaks_ties_by_last_name(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    students.add(
        Student(
            first_name="Анна",
            last_name="Адамчук",
            average_grade=99.5,
            group=groups_by_name["PI-21"],
        )
    )
    best = students.best()
    assert best is not None
    assert best.last_name == "Адамчук"


def test_best_of_empty_table_is_none(session: Session) -> None:
    assert StudentRepository(session).best() is None


def test_group_average_uses_sql_avg(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    assert students.group_average(groups_by_name["PI-21"].id) == pytest.approx(
        87.5
    )
    assert students.group_average(groups_by_name["PI-22"].id) == pytest.approx(
        (99.5 + 55 + 80) / 3
    )


def test_group_average_of_empty_group_is_none(
    students: StudentRepository, groups_by_name: dict[str, Group]
) -> None:
    assert students.group_average(groups_by_name["PI-23"].id) is None


@pytest.fixture
def group_repo(session: Session) -> GroupRepository:
    return GroupRepository(session)


def test_create_assigns_primary_key_and_persists_the_group(
    group_repo: GroupRepository, session: Session, query: Query
) -> None:
    group = group_repo.create("PI-21")
    session.commit()
    assert group.id is not None
    assert query("SELECT name FROM groups") == [("PI-21",)]


def test_get_by_name_finds_existing_group(group_repo: GroupRepository) -> None:
    created = group_repo.create("PI-22")
    assert group_repo.get_by_name("PI-22") is created


def test_get_by_name_of_unknown_group_is_none(
    group_repo: GroupRepository,
) -> None:
    assert group_repo.get_by_name("PI-99") is None


def test_get_by_id_returns_group_or_none(group_repo: GroupRepository) -> None:
    created = group_repo.create("PI-21")
    assert group_repo.get_by_id(created.id) is created
    assert group_repo.get_by_id(999) is None


def test_duplicate_name_violates_unique_constraint(
    group_repo: GroupRepository,
) -> None:
    group_repo.create("PI-21")
    with pytest.raises(
        IntegrityError, match="UNIQUE constraint failed: groups.name"
    ):
        group_repo.create("PI-21")


def test_get_all_is_ordered_and_paginated(group_repo: GroupRepository) -> None:
    for name in ("PI-21", "PI-22", "PI-23", "PI-24"):
        group_repo.create(name)
    assert [g.name for g in group_repo.get_all()] == [
        "PI-21",
        "PI-22",
        "PI-23",
        "PI-24",
    ]
    assert [g.name for g in group_repo.get_all(limit=2, offset=1)] == [
        "PI-22",
        "PI-23",
    ]
    assert group_repo.get_all(limit=10, offset=10) == []


def test_count_follows_inserts_and_deletes(
    group_repo: GroupRepository,
) -> None:
    assert group_repo.count() == 0
    first = group_repo.create("PI-21")
    group_repo.create("PI-22")
    assert group_repo.count() == 2
    assert group_repo.delete(first.id) is True
    assert group_repo.count() == 1


def test_delete_of_unknown_group_returns_false(
    group_repo: GroupRepository,
) -> None:
    assert group_repo.delete(404) is False


def test_stats_aggregate_students_per_group_and_keep_empty_groups(
    group_repo: GroupRepository, session: Session
) -> None:
    first, second = group_repo.create("PI-21"), group_repo.create("PI-22")
    group_repo.create("PI-23")
    session.add_all(
        [
            Student(
                first_name="Олена",
                last_name="Коваленко",
                average_grade=90.0,
                group=first,
            ),
            Student(
                first_name="Андрій",
                last_name="Мельник",
                average_grade=80.0,
                group=first,
            ),
            Student(
                first_name="Ірина",
                last_name="Бондар",
                average_grade=99.5,
                group=second,
            ),
        ]
    )
    session.flush()
    stats = group_repo.stats()
    assert [(s.name, s.students, s.best, s.worst) for s in stats] == [
        ("PI-21", 2, 90.0, 80.0),
        ("PI-22", 1, 99.5, 99.5),
        ("PI-23", 0, None, None),
    ]
    assert [s.average for s in stats[:2]] == [
        pytest.approx(85.0),
        pytest.approx(99.5),
    ]
    assert stats[2].average is None
    assert isinstance(stats[0], GroupStats)


def test_stats_of_empty_database_is_empty(group_repo: GroupRepository) -> None:
    assert group_repo.stats() == []


def test_deleting_group_removes_its_students(
    group_repo: GroupRepository, session: Session, query: Query
) -> None:
    group = group_repo.create("PI-21")
    session.add(
        Student(
            first_name="Олена",
            last_name="Коваленко",
            average_grade=90,
            group=group,
        )
    )
    session.commit()
    assert group_repo.delete(group.id) is True
    session.commit()
    assert query("SELECT count(*) FROM students") == [(0,)]


def test_group_object_is_a_mapped_entity(group_repo: GroupRepository) -> None:
    assert isinstance(group_repo.create("PI-21"), Group)
