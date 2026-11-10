"""Конфігурація застосунку: environment variables і локальний .env.

Секретів у коді немає: API_TOKEN і пароль у DATABASE_URL надходять лише зі
змінних середовища, файлу .env (він в .gitignore та .dockerignore) або
secrets платформи. SecretStr не показує значення в repr і журналах.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def safe_url(url: str) -> str:
    """URL бази для журналу: пароль, якщо він є, замінено на ***."""
    parsed = make_url(url)
    if parsed.password is None:
        return url
    return parsed.render_as_string(hide_password=True)


class Settings(BaseSettings):
    """Налаштування застосунку з environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Student Manager API"
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
    database_url: str = "sqlite:///students.db"
    log_level: LogLevel = "INFO"
    batch_concurrency: int = Field(default=5, ge=1, le=64)
    batch_timeout: float = Field(default=10.0, gt=0, le=300)
    api_token: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def upper_level(cls, value: object) -> object:
        """Рівень журналу без урахування регістру: info -> INFO."""
        return value.upper() if isinstance(value, str) else value

    @field_validator("api_token", mode="before")
    @classmethod
    def empty_token_is_unset(cls, value: object) -> object:
        """API_TOKEN= у .env означає «не задано», а не порожній пароль."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def safe_database_url(self) -> str:
        """URL бази для журналу: пароль замінено на ***."""
        return safe_url(self.database_url)

    @property
    def is_production(self) -> bool:
        """True у production-середовищі."""
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Налаштування читаються один раз за процес (зміна - перезапуск)."""
    return Settings()
