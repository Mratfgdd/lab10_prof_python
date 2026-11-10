"""Асинхронний клієнт: Task, gather, Semaphore, retry."""

import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI
from support import Serve

from student_manager.api import create_app
from student_manager.external_api import (
    ApiUnavailableError,
    GroupSummary,
    RetryPolicy,
    StudentApiClient,
    SummaryError,
    describe,
    groups_word,
)

pytestmark = pytest.mark.asyncio


def statistics_json(group_id: int) -> dict[str, object]:
    return {
        "group_id": group_id,
        "name": f"PI-{20 + group_id}",
        "students_count": 3,
        "average_grade": 80.5,
        "best_grade": 95.0,
        "worst_grade": 60.0,
    }


def fake_api(
    *,
    latency: float = 0.0,
    fail_first: int = 0,
    status: int = 503,
    stats: dict[str, int] | None = None,
) -> httpx.MockTransport:
    counters = stats if stats is not None else {}
    counters.update(calls=0, in_flight=0, max_in_flight=0)

    async def handler(request: httpx.Request) -> httpx.Response:
        counters["calls"] += 1
        counters["in_flight"] += 1
        counters["max_in_flight"] = max(
            counters["max_in_flight"], counters["in_flight"]
        )
        try:
            await asyncio.sleep(latency)
            if counters["calls"] <= fail_first:
                return httpx.Response(status, json={"detail": "temporary"})
            return httpx.Response(
                200, json=statistics_json(int(request.url.path.split("/")[2]))
            )
        finally:
            counters["in_flight"] -= 1

    return httpx.MockTransport(handler)


async def test_summary_through_the_real_application(
    api: StudentApiClient, client: httpx.AsyncClient
) -> None:
    for name in ("PI-21", "PI-22"):
        await client.post("/groups", json={"name": name})
    await client.post(
        "/students",
        json={
            "first_name": "Олена",
            "last_name": "Коваленко",
            "group_id": 1,
            "average_grade": 90,
        },
    )
    results = await api.groups_summary([1, 2, 999])
    assert results[0] == GroupSummary(1, "PI-21", 1, 90.0, 90.0, 90.0)
    assert results[1] == GroupSummary(2, "PI-22", 0, None, None, None)
    assert results[2] == SummaryError(
        999, "HTTP 404: групу з id=999 не знайдено"
    )
    assert api.requests_sent == 3


async def test_results_keep_the_order_of_the_requested_ids() -> None:
    async with StudentApiClient(transport=fake_api(latency=0.01)) as api:
        results = await api.groups_summary([5, 1, 3])
    assert [r.group_id for r in results if isinstance(r, GroupSummary)] == [
        5,
        1,
        3,
    ]


async def test_semaphore_limits_concurrent_requests() -> None:
    stats: dict[str, int] = {}
    async with StudentApiClient(
        transport=fake_api(latency=0.02, stats=stats), max_concurrency=3
    ) as api:
        results = await api.groups_summary(list(range(1, 11)))
    assert all(isinstance(r, GroupSummary) for r in results)
    assert (stats["calls"], stats["max_in_flight"]) == (10, 3)


async def test_tasks_and_gather_run_requests_in_parallel() -> None:
    async with StudentApiClient(
        transport=fake_api(latency=0.05), max_concurrency=10
    ) as api:
        started = time.perf_counter()
        await api.groups_summary(list(range(1, 11)))
        elapsed = time.perf_counter() - started
    assert elapsed < 0.35


async def test_retry_with_backoff_recovers_from_503(
    fast_retry: RetryPolicy,
) -> None:
    stats: dict[str, int] = {}
    async with StudentApiClient(
        transport=fake_api(fail_first=2, stats=stats), retry=fast_retry
    ) as api:
        started = time.perf_counter()
        data = await api.get_json("/groups/1/statistics")
    assert data["name"] == "PI-21"
    assert stats["calls"] == 3
    assert time.perf_counter() - started >= 0.01 + 0.02


async def test_retry_gives_up_after_all_attempts(
    fast_retry: RetryPolicy,
) -> None:
    async with StudentApiClient(
        transport=fake_api(fail_first=99), retry=fast_retry
    ) as api:
        with pytest.raises(
            ApiUnavailableError, match="HTTP 503 після 3 спроб"
        ):
            await api.get_json("/groups/1/statistics")
        assert api.requests_sent == 3


async def test_client_errors_are_not_retried(fast_retry: RetryPolicy) -> None:
    async with StudentApiClient(
        transport=fake_api(fail_first=99, status=404), retry=fast_retry
    ) as api:
        with pytest.raises(httpx.HTTPStatusError):
            await api.get_json("/groups/1/statistics")
        assert api.requests_sent == 1


async def test_connection_error_is_retried(fast_retry: RetryPolicy) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=statistics_json(1))

    async with StudentApiClient(
        transport=httpx.MockTransport(handler), retry=fast_retry
    ) as api:
        assert (await api.get_json("/groups/1/statistics"))["group_id"] == 1
    assert calls == 2


async def test_deadline_cancels_unfinished_tasks() -> None:
    async with StudentApiClient(transport=fake_api(latency=5)) as api:
        started = time.perf_counter()
        with pytest.raises(TimeoutError):
            await api.groups_summary([1, 2, 3], deadline=0.2)
    assert time.perf_counter() - started < 1
    assert [
        t for t in asyncio.all_tasks() if t.get_name().startswith("group-")
    ] == []


async def test_request_timeout_on_a_real_server(serve: Serve) -> None:
    slow = FastAPI()

    @slow.get("/groups/{group_id}/statistics")
    async def slow_statistics(group_id: int) -> dict[str, object]:
        await asyncio.sleep(2)
        return statistics_json(group_id)

    base_url = serve(slow)
    retry = RetryPolicy(attempts=2, backoff=0.05)
    async with StudentApiClient(base_url, timeout=0.2, retry=retry) as api:
        started = time.perf_counter()
        with pytest.raises(
            ApiUnavailableError, match="ReadTimeout після 2 спроб"
        ):
            await api.get_json("/groups/1/statistics")
    assert 0.4 <= time.perf_counter() - started < 1.5


async def test_end_to_end_over_tcp(serve: Serve, api_db_url: str) -> None:
    base_url = serve(create_app(api_db_url))
    async with httpx.AsyncClient(base_url=base_url) as http:
        await http.post("/groups", json={"name": "PI-21"})
        await http.post("/groups", json={"name": "PI-22"})
    async with StudentApiClient(base_url, max_concurrency=2) as api:
        results = await api.groups_summary([1, 2])
    assert [
        (r.name, r.students) for r in results if isinstance(r, GroupSummary)
    ] == [
        ("PI-21", 0),
        ("PI-22", 0),
    ]


async def test_one_http_client_is_reused_and_closed_on_exit() -> None:
    async with StudentApiClient(transport=fake_api()) as api:
        await api.groups_summary([1, 2, 3])
        assert not api.is_closed
    assert api.is_closed


async def test_describe_handles_non_json_error_bodies() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="plain text")

    async with StudentApiClient(transport=httpx.MockTransport(handler)) as api:
        results = await api.groups_summary([1])
    assert results == [SummaryError(1, "HTTP 404: Not Found")]
    assert describe(RuntimeError("boom")) == "RuntimeError: boom"


@pytest.mark.parametrize(
    ("attempt", "delay"),
    [(1, 0.25), (2, 0.5), (3, 1.0), (4, 2.0)],
    ids=str,
)
async def test_backoff_doubles_after_every_attempt(
    attempt: int, delay: float
) -> None:
    assert RetryPolicy().delay(attempt) == delay


@pytest.mark.parametrize(
    ("number", "word"),
    [(1, "група"), (2, "групи"), (5, "груп"), (11, "груп"), (21, "група")],
)
async def test_groups_word_agrees_with_the_number(
    number: int, word: str
) -> None:
    assert groups_word(number) == word
