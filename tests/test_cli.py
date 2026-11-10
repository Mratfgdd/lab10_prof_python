"""Консольний застосунок student-manager."""

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import create_autospec

import pytest
from alembic import command
from alembic.config import Config
from support import Query, SetEnv

from student_manager.exceptions import StudentManagerError
from student_manager.main import HANDLERS, main
from student_manager.services import StudentService

Run = Callable[..., tuple[int, str, str]]


@pytest.fixture
def cli(
    alembic_cfg: Config, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> Run:
    command.upgrade(alembic_cfg, "head")
    capsys.readouterr()

    def run(*argv: str) -> tuple[int, str, str]:
        code = main(["--db", f"sqlite:///{db_path}", *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


@pytest.fixture
def seeded(cli: Run) -> Run:
    assert cli("seed")[0] == 0
    return cli


def test_seed_creates_groups_and_students(cli: Run, query: Query) -> None:
    code, out, _ = cli("seed")
    assert code == 0
    assert "Створено груп: 3, студентів: 9" in out
    assert query("SELECT count(*) FROM students") == [(9,)]


def test_seed_twice_does_not_duplicate_data(seeded: Run, query: Query) -> None:
    code, out, _ = seeded("seed")
    assert code == 0
    assert "seed пропущено" in out
    assert query("SELECT count(*) FROM students") == [(9,)]


def test_groups_report_shows_counts_and_averages(seeded: Run) -> None:
    _, out, _ = seeded("groups")
    assert "PI-21          3     86.17  95.00  78.00" in out
    assert out.count("PI-2") == 3


def test_students_listing_filters_and_sorts(seeded: Run) -> None:
    _, out, _ = seeded(
        "students", "--group", "PI-22", "--sort", "average_grade", "--desc"
    )
    names = [line.split()[1] for line in out.splitlines()[1:]]
    assert names == ["Бондар", "Гнатишин", "Гриценко"]


def test_students_listing_supports_min_grade_and_pages(seeded: Run) -> None:
    _, out, _ = seeded(
        "students",
        "--min-grade",
        "90",
        "--limit",
        "2",
        "--sort",
        "average_grade",
    )
    assert len(out.splitlines()) == 3
    assert "Гнатишин" in out


def test_find_by_last_name(seeded: Run) -> None:
    code, out, _ = seeded("find", "Бондар")
    assert code == 0
    assert "iryna.bondar@example.com" in out


def test_find_of_unknown_last_name_reports_nothing_found(seeded: Run) -> None:
    code, out, _ = seeded("find", "Ніхто")
    assert code == 0
    assert "не знайдено" in out


def test_by_group_and_dbapi_group_return_the_same_students(
    seeded: Run,
) -> None:
    _, orm_out, _ = seeded("by-group", "PI-21")
    _, dbapi_out, _ = seeded("dbapi-group", "PI-21")
    orm_names = {line.split()[1] for line in orm_out.splitlines()[1:]}
    dbapi_names = {line.split()[1] for line in dbapi_out.splitlines()}
    assert orm_names == dbapi_names == {"Бойко", "Коваленко", "Мельник"}


def test_dbapi_group_does_not_execute_injected_sql(
    seeded: Run, query: Query
) -> None:
    code, out, _ = seeded("dbapi-group", "PI-21' OR '1'='1")
    assert code == 0
    assert "не знайдено" in out
    assert query("SELECT count(*) FROM students") == [(9,)]


def test_add_student(seeded: Run, query: Query) -> None:
    code, out, _ = seeded(
        "add",
        "Назар",
        "Левандівський",
        "PI-21",
        "88.5",
        "--email",
        "n@example.com",
    )
    assert code == 0
    assert "Додано: 10 Левандівський Назар" in out
    assert query("SELECT email FROM students WHERE id = 10") == [
        ("n@example.com",)
    ]


def test_add_student_to_unknown_group_fails_with_message(seeded: Run) -> None:
    code, _, err = seeded("add", "Назар", "Левандівський", "PI-99", "88")
    assert code == 1
    assert "Помилка: групу PI-99 не знайдено" in err


def test_invalid_grade_fails_without_changes(
    seeded: Run, query: Query
) -> None:
    code, _, err = seeded("grade", "1", "150")
    assert code == 1
    assert "поза діапазоном" in err
    assert query("SELECT average_grade FROM students WHERE id = 1") == [
        (95.0,)
    ]


def test_grade_update(seeded: Run, query: Query) -> None:
    code, out, _ = seeded("grade", "2", "81.25")
    assert code == 0
    assert "81.25" in out
    assert query("SELECT average_grade FROM students WHERE id = 2") == [
        (81.25,)
    ]


def test_email_update_and_duplicate(seeded: Run) -> None:
    assert seeded("email", "2", "andrii@example.com")[0] == 0
    code, _, err = seeded("email", "3", "ANDRII@example.com")
    assert code == 1
    assert "уже використовується" in err


def test_transfer_moves_students(seeded: Run, query: Query) -> None:
    code, out, _ = seeded("transfer", "PI-23", "1", "2")
    assert code == 0
    assert "Переведено студентів: 2 -> PI-23" in out
    assert query("SELECT count(*) FROM students WHERE group_id = 3") == [(5,)]


def test_transfer_with_missing_student_changes_nothing(
    seeded: Run, query: Query
) -> None:
    code, _, err = seeded("transfer", "PI-23", "1", "2", "777")
    assert code == 1
    assert "id=777" in err
    assert query("SELECT count(*) FROM students WHERE group_id = 3") == [(3,)]


def test_delete_student_and_missing_student(seeded: Run, query: Query) -> None:
    assert seeded("delete", "1")[0] == 0
    assert query("SELECT count(*) FROM students") == [(8,)]
    code, _, err = seeded("delete", "1")
    assert (code, "не знайдено" in err) == (1, True)


def test_delete_group_requires_force_when_it_has_students(
    seeded: Run, query: Query
) -> None:
    code, _, err = seeded("delete-group", "PI-23")
    assert code == 1
    assert "є студенти" in err
    code, out, _ = seeded("delete-group", "PI-23", "--force")
    assert code == 0
    assert "студентів разом з нею: 3" in out
    assert query("SELECT count(*) FROM students") == [(6,)]


def test_best_student_and_average(seeded: Run) -> None:
    assert "Бондар Ірина (PI-22, 99.5)" in seeded("best")[1]
    assert "Середній бал PI-21: 86.17" in seeded("average", "PI-21")[1]


def test_best_on_empty_database(cli: Run) -> None:
    code, out, _ = cli("best")
    assert code == 0
    assert "Студентів ще немає" in out


def test_missing_schema_is_reported_with_a_hint(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--db", f"sqlite:///{db_path}", "groups"])
    assert code == 1
    assert "alembic upgrade head" in capsys.readouterr().err


def test_database_url_can_come_from_the_environment(
    alembic_cfg: Config,
    db_path: Path,
    set_env: SetEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(alembic_cfg, "head")
    set_env(database_url=f"sqlite:///{db_path}")
    capsys.readouterr()
    assert main(["seed"]) == 0
    assert "студентів: 9" in capsys.readouterr().out


def test_unknown_command_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["unknown"])
    assert raised.value.code == 2


def test_dbapi_search_needs_a_file_database() -> None:
    namespace = argparse.Namespace(command="dbapi-group", group="PI-21")
    service = create_autospec(StudentService, instance=True)
    with pytest.raises(StudentManagerError, match="файлової бази"):
        HANDLERS["dbapi-group"](namespace, service, "sqlite://")
    assert service.method_calls == []


def test_serve_command_starts_uvicorn_with_the_given_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        "student_manager.main.uvicorn.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    assert main(["serve", "--port", "9001", "--no-migrate"]) == 0
    assert calls == [
        (
            ("student_manager.api:app",),
            {"host": "127.0.0.1", "port": 9001, "log_level": "info"},
        )
    ]
