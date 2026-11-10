"""Середовище Alembic: метадані моделей і URL бази."""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, create_engine, event, pool

from student_manager.database import database_url
from student_manager.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    """URL бази: з налаштувань Alembic або зі змінної середовища."""
    return config.get_main_option("sqlalchemy.url") or database_url()


def run_migrations_offline() -> None:
    """Режим --sql: друк SQL без підключення до БД."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Виконує міграції в одній транзакції з явним BEGIN."""
    connectable = create_engine(_url(), poolclass=pool.NullPool)

    @event.listens_for(connectable, "connect")
    def _no_driver_transactions(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(connectable, "begin")
    def _begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN")

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
