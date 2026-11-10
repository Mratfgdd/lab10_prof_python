"""Залежності FastAPI: налаштування, спільні ресурси, сесія й сервіс."""

from __future__ import annotations

import asyncio
import secrets
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated, TypeVar

from fastapi import Depends, FastAPI, Header, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from student_manager.caching import StatisticsCache
from student_manager.config import Settings
from student_manager.database import (
    ensure_schema,
    make_engine,
    make_session_factory,
)
from student_manager.exceptions import UnauthorizedError
from student_manager.services import StudentService

T = TypeVar("T")
RUNTIME_LOCK = threading.Lock()


@dataclass(slots=True)
class Runtime:
    """Спільні ресурси: engine, сесії, Semaphore пакетних запитів і кеш."""

    engine: Engine
    session_factory: sessionmaker[Session]
    batch_semaphore: asyncio.Semaphore
    batch_timeout: float
    cache: StatisticsCache


def get_runtime(app: FastAPI) -> Runtime:
    """Повертає Runtime застосунку, створюючи його під час першого виклику."""
    with RUNTIME_LOCK:
        runtime: Runtime | None = getattr(app.state, "runtime", None)
        if runtime is None:
            settings: Settings = app.state.settings
            engine = make_engine(settings.database_url)
            try:
                ensure_schema(engine)
            except Exception:
                engine.dispose()
                raise
            runtime = Runtime(
                engine,
                make_session_factory(engine),
                asyncio.Semaphore(settings.batch_concurrency),
                settings.batch_timeout,
                StatisticsCache(),
            )
            app.state.runtime = runtime
        return runtime


def close_runtime(app: FastAPI) -> None:
    """Закриває з'єднання з БД і забуває Runtime."""
    with RUNTIME_LOCK:
        runtime: Runtime | None = getattr(app.state, "runtime", None)
        app.state.runtime = None
    if runtime is not None:
        runtime.engine.dispose()


def get_session(request: Request) -> Iterator[Session]:
    """Видає окрему сесію БД на кожен запит і закриває її після відповіді."""
    with get_runtime(request.app).session_factory() as session:
        yield session


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> StudentService:
    """Створює сервіс шару збереження поверх сесії запиту."""
    return StudentService(session, get_runtime(request.app).cache)


def require_token(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Якщо задано API_TOKEN, зміни даних потребують заголовок X-API-Key."""
    settings: Settings = request.app.state.settings
    token = settings.api_token
    if token is None:
        return
    expected = token.get_secret_value().encode()
    given = (x_api_key or "").encode()
    if not secrets.compare_digest(given, expected):
        raise UnauthorizedError("потрібен чинний заголовок X-API-Key")


ServiceDep = Annotated[StudentService, Depends(get_service)]
StudentId = Annotated[int, PathParam(gt=0, description="id студента")]
GroupId = Annotated[int, PathParam(gt=0, description="id групи")]


async def in_thread(function: Callable[[], T]) -> T:
    """Виконує синхронний виклик у пулі потоків, не блокуючи event loop."""
    return await run_in_threadpool(function)
