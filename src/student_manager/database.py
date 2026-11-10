"""Підключення до БД: engine, сесії, перевірка схеми, міграції."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, make_url
from sqlalchemy.orm import Session, sessionmaker

from student_manager.config import get_settings
from student_manager.exceptions import SchemaMissingError

MIGRATIONS = Path(__file__).with_name("migrations")


def database_url() -> str:
    """URL бази з налаштувань (змінна середовища DATABASE_URL)."""
    return get_settings().database_url


def alembic_config(url: str) -> Config:
    """Конфігурація Alembic без ini-файлу: скрипти лежать у пакеті."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


def migrate(url: str | None = None, revision: str = "head") -> None:
    """Застосовує міграції (alembic upgrade); для SQLite створює каталог."""
    target = url or database_url()
    database = make_url(target).database
    if make_url(target).get_backend_name() == "sqlite" and database:
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(target), revision)


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Створює engine; для SQLite вмикає FOREIGN KEY і casefold."""
    engine = create_engine(url or database_url(), echo=echo)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _configure_connection)
    return engine


def _casefold(value: str | None) -> str | None:
    """SQL-функція casefold: порівняння без урахування регістру."""
    return None if value is None else value.casefold()


def _configure_connection(
    dbapi_connection: Any, _connection_record: Any
) -> None:
    """Налаштовує нове з'єднання SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()
    dbapi_connection.create_function(
        "casefold", 1, _casefold, deterministic=True
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Фабрика сесій без autoflush і без закінчення дії об'єктів."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_schema(engine: Engine) -> None:
    """Перевіряє, що міграції Alembic виконано."""
    if not inspect(engine).has_table("alembic_version"):
        raise SchemaMissingError(
            "БД не ініціалізовано: виконайте alembic upgrade head"
        )
