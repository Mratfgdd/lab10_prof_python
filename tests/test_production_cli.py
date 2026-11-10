"""Production-команди: --version, config, migrate, serve і логування."""

import logging
from pathlib import Path
from typing import Any

import pytest
from support import SetEnv

from student_manager import __version__
from student_manager.database import ensure_schema, make_engine
from student_manager.main import configure_logging, main


def test_version_flag_prints_the_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == f"student-manager {__version__}"


def test_config_command_shows_effective_settings(
    set_env: SetEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    set_env(environment="production", log_level="warning")
    assert main(["config"]) == 0
    output = capsys.readouterr().out
    assert "ENVIRONMENT        production" in output
    assert "LOG_LEVEL          WARNING" in output
    assert "API_TOKEN          (не задано)" in output


def test_config_command_never_prints_the_secret_values(
    set_env: SetEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    set_env(
        api_token="unit-test-token",
        database_url="postgresql://app:hunter2@db/students",
    )
    assert main(["config"]) == 0
    output = capsys.readouterr().out
    assert "unit-test-token" not in output
    assert "hunter2" not in output
    assert "app:***@db" in output


def test_migrate_command_creates_the_schema(
    tmp_path: Path, set_env: SetEnv
) -> None:
    target = tmp_path / "var" / "students.db"
    set_env(database_url=f"sqlite:///{target}")
    assert main(["migrate"]) == 0
    engine = make_engine(f"sqlite:///{target}")
    try:
        ensure_schema(engine)
    finally:
        engine.dispose()


def test_migrate_command_accepts_the_db_option(tmp_path: Path) -> None:
    target = tmp_path / "other.db"
    assert main(["--db", f"sqlite:///{target}", "migrate"]) == 0
    assert target.exists()


def test_serve_applies_migrations_before_starting_uvicorn(
    tmp_path: Path, set_env: SetEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "served.db"
    set_env(database_url=f"sqlite:///{target}", log_level="DEBUG")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "student_manager.main.uvicorn.run",
        lambda *args, **kwargs: calls.append({"target": args[0], **kwargs}),
    )
    assert main(["serve", "--host", "0.0.0.0", "--port", "9100"]) == 0
    assert target.exists()
    assert calls == [
        {
            "target": "student_manager.api:app",
            "host": "0.0.0.0",
            "port": 9100,
            "log_level": "debug",
        }
    ]


def test_serve_can_skip_migrations(
    tmp_path: Path, set_env: SetEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "skipped.db"
    set_env(database_url=f"sqlite:///{target}")
    monkeypatch.setattr("student_manager.main.uvicorn.run", lambda *a, **k: 0)
    assert main(["serve", "--no-migrate"]) == 0
    assert not target.exists()


def test_configure_logging_sets_level_and_format() -> None:
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    try:
        configure_logging("DEBUG")
        assert root.level == logging.DEBUG
        formatter = root.handlers[0].formatter
        assert formatter is not None
        record = logging.LogRecord(
            "student_manager", logging.INFO, __file__, 1, "ok", None, None
        )
        assert " INFO student_manager ok" in formatter.format(record)
    finally:
        root.handlers[:] = saved[1]
        root.setLevel(saved[0])
