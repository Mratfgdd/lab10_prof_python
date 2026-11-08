"""Підключення до БД: engine, FOREIGN KEY у SQLite, фабрика сесій, міграції Alembic."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from bank_account_service.config import get_settings
from bank_account_service.exceptions import SchemaMissingError

MIGRATIONS = Path(__file__).with_name("migrations")


def database_url() -> str:
    """URL бази з конфігурації (змінна середовища DATABASE_URL)."""
    return get_settings().database_url


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    engine = create_engine(url or database_url(), echo=echo)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_schema(engine: Engine) -> None:
    """Схему створюють міграції Alembic; застосунок лише перевіряє, що вони виконані."""
    if not inspect(engine).has_table("alembic_version"):
        raise SchemaMissingError("БД не ініціалізовано: виконайте bank-account-service migrate")


def database_ready(engine: Engine) -> bool:
    """Для /health: з'єднання працює і схема створена міграціями."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return inspect(engine).has_table("alembic_version")
    except Exception:  # noqa: BLE001
        return False


def migrate(url: str | None = None) -> None:
    """alembic upgrade head з каталогу migrations усередині пакета: працює і з
    встановленого wheel (у Docker), де немає alembic.ini проєкту."""
    target = url or database_url()
    parsed = make_url(target)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", target)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
