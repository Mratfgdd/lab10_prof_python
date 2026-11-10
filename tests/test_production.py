"""Готовність до production: файли розгортання, секрети, метадані пакета."""

import tomllib

import pytest
from support import PROJECT_ROOT

from student_manager import __version__
from student_manager.api import app
from student_manager.config import Settings
from student_manager.main import main

SETTINGS_ENV = {"APP_NAME", "ENVIRONMENT", "DATABASE_URL", "LOG_LEVEL"}


def read(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def env_names(text: str) -> set[str]:
    return {
        line.split("=", 1)[0]
        for line in text.splitlines()
        if "=" in line and not line.startswith("#")
    }


def test_env_example_lists_every_setting() -> None:
    names = env_names(read(".env.example"))
    assert SETTINGS_ENV <= names
    schema = Settings.model_json_schema()["properties"]
    fields = {name.upper() for name in schema}
    assert names <= fields | {"APP_ENV"}


def test_env_example_has_no_secret_values() -> None:
    values = dict(
        line.split("=", 1)
        for line in read(".env.example").splitlines()
        if "=" in line
    )
    assert values["API_TOKEN"] == ""
    assert not (PROJECT_ROOT / ".env").exists()


@pytest.mark.parametrize("name", [".gitignore", ".dockerignore"])
def test_dotenv_is_ignored_by_git_and_docker(name: str) -> None:
    lines = read(name).splitlines()
    assert ".env" in lines
    assert "*.db" in lines


def test_version_is_single_sourced() -> None:
    metadata = tomllib.loads(read("pyproject.toml"))
    assert metadata["project"]["version"] == __version__
    assert metadata["project"]["name"] == "student-manager"
    assert metadata["project"]["scripts"]["student-manager"] == (
        "student_manager.main:main"
    )


def test_package_metadata_is_complete() -> None:
    project = tomllib.loads(read("pyproject.toml"))["project"]
    for key in ("description", "readme", "license", "authors", "classifiers"):
        assert project[key]
    assert (
        (PROJECT_ROOT / "LICENSE")
        .read_text(encoding="utf-8")
        .startswith("MIT License")
    )
    assert project["requires-python"] == ">=3.11"


def test_package_data_covers_static_files_and_migrations() -> None:
    package_data = tomllib.loads(read("pyproject.toml"))["tool"]["setuptools"][
        "package-data"
    ]
    assert "static/*" in package_data["student_manager"]
    assert package_data["student_manager.migrations"] == ["script.py.mako"]
    base = PROJECT_ROOT / "src" / "student_manager"
    assert (base / "py.typed").exists()
    assert (base / "migrations" / "script.py.mako").exists()
    assert (base / "migrations" / "versions" / "__init__.py").exists()


def test_dockerfile_is_production_ready() -> None:
    text = read("Dockerfile")
    assert text.count("FROM ") == 2
    assert "AS builder" in text
    assert "USER appuser" in text
    assert "HEALTHCHECK" in text
    assert 'VOLUME ["/app/data"]' in text
    assert "/health" in text
    assert "EXPOSE 8000" in text
    assert '"student-manager", "serve"' in text


def test_dockerfile_has_no_credentials() -> None:
    text = read("Dockerfile").lower()
    for word in ("password", "token", "secret", "api_key"):
        assert word not in text


def test_dockerfile_entry_point_exists() -> None:
    assert callable(main)
    assert app.title


def test_ci_workflow_runs_every_required_check() -> None:
    text = read(".github/workflows/ci.yml")
    for command in (
        "ruff check .",
        "ruff format --check .",
        "mypy",
        "pytest",
        "python -m build",
        "docker build",
        "docker run",
        "tools/check_secrets.py",
    ):
        assert command in text
    assert '["3.11", "3.12"]' in text


def test_ci_does_not_contain_a_real_token() -> None:
    text = read(".github/workflows/ci.yml")
    assert "openssl rand" in text
    assert "ghp_" not in text


def test_readme_documents_the_required_sections() -> None:
    text = read("README.md")
    for heading in (
        "## Встановлення",
        "## Конфігурація",
        "## Запуск",
        "## Docker",
        "## API",
        "## Тести",
        "## CI/CD",
        "## Демонстрація",
    ):
        assert heading in text
    for endpoint in (
        "/health",
        "/students",
        "/groups/{group_id}/students",
        "/groups/{group_id}/statistics",
    ):
        assert endpoint in text


def test_no_absolute_user_paths_in_the_project() -> None:
    markers = ("C:\\Users", "C:/Users", "/home/", "/Users/")
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(marker in text for marker in markers), path
    for name in ("Dockerfile", "README.md", "pyproject.toml"):
        text = read(name)
        assert not any(marker in text for marker in markers[:2]), name
