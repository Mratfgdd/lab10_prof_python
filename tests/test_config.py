"""Конфігурація: значення за замовчуванням, environment variables, секрети."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from support import SetEnv

from student_manager.config import Settings, get_settings, safe_url


def test_defaults_are_safe_for_local_development() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.database_url == "sqlite:///students.db"
    assert settings.log_level == "INFO"
    assert settings.api_token is None
    assert not settings.is_production


def test_environment_variables_override_defaults(set_env: SetEnv) -> None:
    set_env(
        environment="production",
        database_url="sqlite:////data/prod.db",
        log_level="debug",
        app_name="Campus API",
        batch_concurrency="9",
        batch_timeout="2.5",
    )
    settings = get_settings()
    assert settings.environment == "production"
    assert settings.is_production
    assert settings.database_url == "sqlite:////data/prod.db"
    assert settings.log_level == "DEBUG"
    assert settings.app_name == "Campus API"
    assert settings.batch_concurrency == 9
    assert settings.batch_timeout == pytest.approx(2.5)


def test_app_env_is_accepted_as_an_alias_of_environment(
    set_env: SetEnv,
) -> None:
    set_env(app_env="test")
    assert get_settings().environment == "test"


def test_values_are_read_from_a_dotenv_file(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ENVIRONMENT=test\nLOG_LEVEL=warning\nDATABASE_URL=sqlite:///x.db\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=dotenv)
    assert (settings.environment, settings.log_level) == ("test", "WARNING")
    assert settings.database_url == "sqlite:///x.db"


def test_real_environment_wins_over_dotenv(
    tmp_path: Path, set_env: SetEnv
) -> None:
    (tmp_path / ".env").write_text("LOG_LEVEL=ERROR\n", encoding="utf-8")
    set_env(log_level="DEBUG")
    assert Settings().log_level == "DEBUG"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("environment", "staging"),
        ("log_level", "LOUD"),
        ("batch_concurrency", "0"),
        ("batch_concurrency", "1000"),
        ("batch_timeout", "-1"),
    ],
)
def test_invalid_values_are_rejected(
    name: str, value: str, set_env: SetEnv
) -> None:
    set_env(**{name: value})
    with pytest.raises(ValidationError):
        Settings()


def test_token_is_a_secret_and_never_shown(set_env: SetEnv) -> None:
    set_env(api_token="unit-test-token")
    settings = get_settings()
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "unit-test-token"
    assert "unit-test-token" not in repr(settings)
    assert "unit-test-token" not in str(settings.model_dump())


@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_token_means_not_configured(empty: str, set_env: SetEnv) -> None:
    set_env(api_token=empty)
    assert get_settings().api_token is None


def test_password_in_database_url_is_hidden_for_logs() -> None:
    url = "postgresql://app:hunter2@db:5432/students"
    assert safe_url(url) == "postgresql://app:***@db:5432/students"
    assert "hunter2" not in Settings(database_url=url).safe_database_url


def test_sqlite_path_is_shown_unchanged() -> None:
    url = "sqlite:///C:/data/students.db"
    assert safe_url(url) == url
    assert safe_url("sqlite://") == "sqlite://"


def test_settings_are_read_once_per_process(set_env: SetEnv) -> None:
    set_env(log_level="WARNING")
    first = get_settings()
    assert get_settings() is first
