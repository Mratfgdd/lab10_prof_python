"""Fixtures: окрема тестова БД (створена міграціями), налаштування, HTTPX, uvicorn."""

import shutil
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI

from bank_account_service.api import create_app
from bank_account_service.config import Settings
from bank_account_service.database import migrate
from bank_account_service.external_api import BankApiClient

CONFIG_VARIABLES = (
    "APP_NAME",
    "APP_ENV",
    "DATABASE_URL",
    "LOG_LEVEL",
    "CONFLICT_RETRIES",
    "API_TOKEN",
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Тести не залежать від змінних і .env розробника: чисте середовище, cwd - tmp_path."""
    for name in CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Один раз на сесію: порожня БД, створена міграціями (як під час запуску сервісу)."""
    path = tmp_path_factory.mktemp("template") / "bank.db"
    migrate(f"sqlite:///{path}")
    return path


@pytest.fixture
def db_url(migrated_template: Path, tmp_path: Path) -> str:
    """Кожен тест - на власній копії тестової БД у tmp_path."""
    path = tmp_path / "test_bank.db"
    shutil.copy(migrated_template, path)
    return f"sqlite:///{path}"


@pytest.fixture
def settings(db_url: str) -> Settings:
    return Settings(database_url=db_url, app_env="test", _env_file=None)


@pytest_asyncio.fixture
async def asgi_app(settings: Settings) -> AsyncIterator[FastAPI]:
    """Застосунок із тестовою БД; ASGITransport не запускає lifespan, тому - вручну."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client(asgi_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клієнт до застосунку без мережі: запити йдуть прямо в ASGI-застосунок."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def bank(client: httpx.AsyncClient) -> dict[str, int]:
    """Дані створюються через сам API: рахунки UA-1001 (1000 UAH), UA-1002 (250 UAH),
    UA-2001 (100 USD, savings); повертає id клієнтів і рахунків."""
    ids = {}
    for key, name in [("olena", "Олена Коваленко"), ("andrii", "Андрій Мельник")]:
        ids[key] = (await client.post("/clients", json={"full_name": name})).json()["id"]
    for owner, number, balance, currency, kind in [
        ("olena", "UA-1001", "1000.00", "UAH", "current"),
        ("andrii", "UA-1002", "250.00", "UAH", "current"),
        ("olena", "UA-2001", "100.00", "USD", "savings"),
    ]:
        response = await client.post(
            "/accounts",
            json={
                "client_id": ids[owner],
                "number": number,
                "opening_balance": balance,
                "currency": currency,
                "account_type": kind,
            },
        )
        ids[number] = response.json()["id"]
    return ids


@pytest_asyncio.fixture
async def api(asgi_app: FastAPI) -> AsyncIterator[BankApiClient]:
    """Клієнт external_api, що звертається до застосунку без мережі (ASGITransport)."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with BankApiClient("http://test", transport=transport, max_concurrency=3) as client:
        yield client


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def serve() -> Iterator[Callable[[FastAPI], str]]:
    """Запускає застосунок у справжньому uvicorn (окремий потік) і повертає base URL."""
    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def start(app: FastAPI) -> str:
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        servers.append((server, thread))
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("uvicorn не стартував")
            time.sleep(0.02)
        return f"http://127.0.0.1:{port}"

    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=10)
