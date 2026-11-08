"""Точка входу: bank-account-service serve | migrate | config.

serve спершу застосовує міграції (alembic upgrade head), потім запускає uvicorn - тож
контейнер із новою версією сам оновлює схему БД під час розгортання.
"""

import argparse
import logging
import sys
from collections.abc import Sequence

import uvicorn

from bank_account_service import __version__
from bank_account_service.config import Settings, get_settings
from bank_account_service.database import migrate

logger = logging.getLogger("bank_account_service")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True
    )


def show_config(settings: Settings) -> None:
    """Ефективна конфігурація: значення секретів не друкуються."""
    for name, value in settings.model_dump().items():
        if name == "database_url":
            value = settings.safe_database_url
        print(f"{name.upper():<17} {value if value is not None else '(не задано)'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bank-account-service", description="REST API банківських рахунків"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="міграції БД + запуск API (uvicorn)")
    serve.add_argument("--host", default="127.0.0.1", help="0.0.0.0 - лише в контейнері")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-migrate", action="store_true")
    commands.add_parser("migrate", help="застосувати міграції (alembic upgrade head)")
    commands.add_parser("config", help="показати конфігурацію (секрети приховано)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    if args.command == "config":
        show_config(settings)
        return 0
    if args.command == "migrate" or not args.no_migrate:
        migrate(settings.database_url)
        logger.info("migrations applied: %s", settings.safe_database_url)
    if args.command == "serve":
        uvicorn.run(
            "bank_account_service.api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            log_level=settings.log_level.lower(),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
