"""Інструменти: сканер секретів і smoke-тест працюючого API."""

from pathlib import Path

import pytest
from support import PROJECT_ROOT, Serve

import check_secrets
import smoke_test
from student_manager.api import create_app
from student_manager.config import Settings

FAKE = "zxcvbnm98765"
PRIVATE_KEY = "-----BEGIN RSA " + "PRIVATE KEY-----"
GITHUB_CREDENTIAL = "ghp_" + "a" * 36


def test_project_has_no_secrets() -> None:
    checked, findings = check_secrets.scan(PROJECT_ROOT)
    assert checked > 20
    assert not findings


@pytest.mark.parametrize(
    "line",
    [
        f"password = {FAKE!r}",
        f"API_TOKEN = {FAKE!r}",
        f"SECRET_KEY={FAKE}",
        "postgresql://app:" + FAKE + "@db/students",
        PRIVATE_KEY,
        GITHUB_CREDENTIAL,
    ],
)
def test_scanner_detects_secret_like_lines(line: str) -> None:
    assert check_secrets.scan_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "API_TOKEN=",
        "token = secrets.token_hex(16)",
        "sqlite:///students.db",
        'TOKEN = "unit-test-token"',
        "docker run -e API_TOKEN student-manager",
    ],
)
def test_scanner_ignores_safe_lines(line: str) -> None:
    assert not check_secrets.scan_line(line)


def test_scan_reports_file_and_line_and_skips_dotenv(tmp_path: Path) -> None:
    (tmp_path / "settings.py").write_text(
        f"name = 1\npassword = {FAKE!r}\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(f"API_TOKEN={FAKE}\n", encoding="utf-8")
    checked, findings = check_secrets.scan(tmp_path)
    assert checked == 1
    assert len(findings) == 1
    assert findings[0].startswith("settings.py:2:")


def test_scanner_main_returns_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "ok.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_secrets.py", str(tmp_path)])
    assert check_secrets.main() == 0
    (tmp_path / "bad.py").write_text(f"token = {FAKE!r}\n", encoding="utf-8")
    assert check_secrets.main() == 1
    assert "bad.py:1" in capsys.readouterr().out


def test_smoke_exercise_passes_against_a_served_app(
    serve: Serve,
    api_db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(_env_file=None, api_token="unit-test-token")
    base = serve(create_app(api_db_url, settings=settings))
    smoke_test.wait_for_health(base)
    smoke_test.exercise(base, "unit-test-token")
    smoke_test.check_persisted(base, "PI-31")
    assert "OK" in capsys.readouterr().out


def test_smoke_exercise_fails_with_a_wrong_token(
    serve: Serve, api_db_url: str
) -> None:
    settings = Settings(_env_file=None, api_token="unit-test-token")
    base = serve(create_app(api_db_url, settings=settings))
    with pytest.raises(SystemExit):
        smoke_test.exercise(base, "wrong-token")


def test_smoke_main_requires_a_mode() -> None:
    with pytest.raises(SystemExit) as raised:
        smoke_test.main([])
    assert raised.value.code == 2


def test_smoke_main_checks_a_running_server(
    serve: Serve, api_db_url: str
) -> None:
    base = serve(create_app(api_db_url))
    assert smoke_test.main(["--url", base]) == 0
    assert smoke_test.main(["--url", base, "--persisted", "PI-31"]) == 0


def test_free_port_and_venv_paths_are_usable(tmp_path: Path) -> None:
    assert 1024 < smoke_test.free_port() < 65536
    program = smoke_test.venv_program(tmp_path, "python")
    assert Path(program).parent.name in {"Scripts", "bin"}
