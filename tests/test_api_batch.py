"""Пакетна статистика груп: порядок, Semaphore, timeout."""

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from student_manager import api
from student_manager.api import create_app
from student_manager.schemas import GroupStatisticsOut

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def running(
    db_url: str, *, batch_concurrency: int = 5, batch_timeout: float = 10.0
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        db_url,
        batch_concurrency=batch_concurrency,
        batch_timeout=batch_timeout,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as http:
            for name in ("PI-21", "PI-22", "PI-23", "PI-24", "PI-25", "PI-26"):
                await http.post("/groups", json={"name": name})
            await http.post(
                "/students",
                json={
                    "first_name": "Олена",
                    "last_name": "Коваленко",
                    "group_id": 1,
                    "average_grade": 90,
                },
            )
            yield http


async def test_batch_returns_statistics_in_the_order_of_the_request(
    api_db_url: str,
) -> None:
    async with running(api_db_url) as http:
        response = await http.post(
            "/statistics/groups", json={"group_ids": [3, 1, 2]}
        )
    assert response.status_code == 200
    assert [
        (g["group_id"], g["name"], g["students_count"])
        for g in response.json()
    ] == [
        (3, "PI-23", 0),
        (1, "PI-21", 1),
        (2, "PI-22", 0),
    ]


async def test_batch_accepts_repeated_ids(api_db_url: str) -> None:
    async with running(api_db_url) as http:
        response = await http.post(
            "/statistics/groups", json={"group_ids": [1, 1]}
        )
    assert [g["group_id"] for g in response.json()] == [1, 1]


async def test_batch_with_an_unknown_group_is_404_and_leaves_no_running_tasks(
    api_db_url: str,
) -> None:
    async with running(api_db_url) as http:
        response = await http.post(
            "/statistics/groups", json={"group_ids": [1, 999, 2]}
        )
        assert response.status_code == 404
        assert response.json()["error"] == "group_not_found"
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        assert pending == []
        assert (
            await http.post("/statistics/groups", json={"group_ids": [1]})
        ).status_code == 200


async def test_batch_semaphore_limits_the_number_of_concurrent_database_reads(
    api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    original = api.load_statistics

    def tracked(
        factory: sessionmaker[Session], group_id: int
    ) -> GroupStatisticsOut:
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        try:
            time.sleep(0.03)
            return original(factory, group_id)
        finally:
            with lock:
                state["now"] -= 1

    monkeypatch.setattr(api, "load_statistics", tracked)
    async with running(api_db_url, batch_concurrency=2) as http:
        response = await http.post(
            "/statistics/groups", json={"group_ids": [1, 2, 3, 4, 5, 6]}
        )
    assert response.status_code == 200
    assert state["peak"] == 2


async def test_batch_without_a_limit_runs_requests_in_parallel(
    api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = api.load_statistics

    def slow(
        factory: sessionmaker[Session], group_id: int
    ) -> GroupStatisticsOut:
        time.sleep(0.1)
        return original(factory, group_id)

    monkeypatch.setattr(api, "load_statistics", slow)
    async with running(api_db_url, batch_concurrency=6) as http:
        started = time.perf_counter()
        response = await http.post(
            "/statistics/groups", json={"group_ids": [1, 2, 3, 4, 5, 6]}
        )
        elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 0.45


async def test_batch_timeout_is_504_with_structured_error(
    api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = api.load_statistics

    def slow(
        factory: sessionmaker[Session], group_id: int
    ) -> GroupStatisticsOut:
        time.sleep(0.4)
        return original(factory, group_id)

    monkeypatch.setattr(api, "load_statistics", slow)
    async with running(api_db_url, batch_timeout=0.05) as http:
        response = await http.post(
            "/statistics/groups", json={"group_ids": [1, 2]}
        )
    assert response.status_code == 504
    assert response.json() == {
        "error": "batch_timeout",
        "detail": "статистика не отримана за 0.05 с",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"group_ids": []},
        {"group_ids": [0]},
        {"group_ids": list(range(1, 52))},
        {},
        {"ids": [1]},
    ],
    ids=["empty", "zero", "too-many", "missing", "wrong-field"],
)
async def test_batch_validates_the_body(
    client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    assert (
        await client.post("/statistics/groups", json=body)
    ).status_code == 422
