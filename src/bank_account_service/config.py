"""Конфігурація застосунку: environment variables (і .env для локальної розробки).

Секрети не мають значень у коді. API_TOKEN і пароль у DATABASE_URL надходять лише зі
змінних середовища, файлу .env (є в .gitignore і .dockerignore) або secrets платформи
(GitHub Actions secrets, docker run --env-file). SecretStr не показує значення в repr і логах.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bank Account Service"
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///bank.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    conflict_retries: int = Field(default=3, ge=0, le=10)
    api_token: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def upper_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("api_token", mode="before")
    @classmethod
    def empty_token_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def safe_database_url(self) -> str:
        """URL БД для логів: пароль замінено на ***."""
        return make_url(self.database_url).render_as_string(hide_password=True)


@lru_cache
def get_settings() -> Settings:
    """Налаштування читаються один раз за процес (зміна середовища - перезапуск)."""
    return Settings()
