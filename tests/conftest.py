"""Спільні fixtures: тестова БД, ASGI-клієнт, uvicorn."""

import shutil
import socket
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from support import ENV_NAMES, PROJECT_ROOT, Query, Serve, SetEnv

from student_manager.api import create_app
from student_manager.config import get_settings
from student_manager.database import make_engine, make_session_factory
from student_manager.external_api import RetryPolicy, StudentApiClient
from student_manager.models import Base
from student_manager.services import StudentService


@pytest.fixture(autouse=True)
def _clean_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Тести не залежать від змінних середовища й локального .env."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def set_env(monkeypatch: pytest.MonkeyPatch) -> SetEnv:
    """Задає змінні середовища й скидає кеш налаштувань."""

    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name.upper(), value)
        get_settings.cache_clear()

    return apply


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_students.db"


@pytest.fixture
def engine(db_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def service(session: Session) -> StudentService:
    return StudentService(session)


@pytest.fixture
def school(service: StudentService) -> StudentService:
    service.create_group("PI-21")
    service.create_group("PI-22")
    service.create_group("PI-23")
    service.add_student(
        "Олена", "Коваленко", "PI-21", 95.0, "olena@example.com"
    )
    service.add_student("Андрій", "Мельник", "PI-21", 80.0)
    service.add_student("Ірина", "Бондар", "PI-22", 99.5)
    service.add_student("Тарас", "Гриценко", "PI-22", 55.0)
    return service


@pytest.fixture
def query(db_path: Path) -> Query:
    def run(sql: str, *parameters: object) -> list[tuple[Any, ...]]:
        with closing(sqlite3.connect(db_path)) as connection:
            return connection.execute(sql, parameters).fetchall()

    return run


@pytest.fixture
def group_of(query: Query) -> Callable[[int], str]:
    def read(student_id: int) -> str:
        rows = query(
            (
                "SELECT g.name FROM students s JOIN groups g ON g.id = "
                "s.group_id "
                "WHERE s.id = ?"
            ),
            student_id,
        )
        return str(rows[0][0])

    return read


@pytest.fixture
def alembic_cfg(db_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("template") / "template.db"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return path


@pytest.fixture
def api_db_path(migrated_template: Path, tmp_path: Path) -> Path:
    path = tmp_path / "test_api.db"
    shutil.copy(migrated_template, path)
    return path


@pytest.fixture
def api_db_url(api_db_path: Path) -> str:
    return f"sqlite:///{api_db_path}"


@pytest_asyncio.fixture
async def asgi_app(api_db_url: str) -> AsyncIterator[FastAPI]:
    app = create_app(api_db_url)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client(asgi_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def campus(client: httpx.AsyncClient) -> dict[str, int]:
    ids: dict[str, int] = {}
    for name in ("PI-21", "PI-22", "PI-23"):
        ids[name] = (await client.post("/groups", json={"name": name})).json()[
            "group_id"
        ]
    rows = [
        ("Олена", "Коваленко", "PI-21", 95.0, "olena@example.com"),
        ("Андрій", "Мельник", "PI-21", 80.0, None),
        ("Ірина", "Бондар", "PI-22", 99.5, None),
        ("Тарас", "Гриценко", "PI-22", 55.0, None),
    ]
    for first, last, group, grade, email in rows:
        response = await client.post(
            "/students",
            json={
                "first_name": first,
                "last_name": last,
                "group_id": ids[group],
                "average_grade": grade,
                "email": email,
            },
        )
        ids[last] = response.json()["id"]
    return ids


@pytest_asyncio.fixture
async def api(asgi_app: FastAPI) -> AsyncIterator[StudentApiClient]:
    transport = httpx.ASGITransport(app=asgi_app)
    async with StudentApiClient(
        "http://test", transport=transport, max_concurrency=3
    ) as client:
        yield client


@pytest.fixture
def fast_retry() -> RetryPolicy:
    return RetryPolicy(attempts=3, backoff=0.01)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def serve() -> Iterator[Serve]:
    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def start(app: FastAPI) -> str:
        port = free_port()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=1,
        )
        server = uvicorn.Server(config)
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
