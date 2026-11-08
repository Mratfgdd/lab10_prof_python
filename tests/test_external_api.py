"""Асинхронний HTTP-клієнт: Task/gather, Semaphore, retry з backoff, timeout."""

import asyncio
import time
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from bank_account_service.api import create_app
from bank_account_service.config import Settings
from bank_account_service.external_api import (
    AccountOverview,
    ApiUnavailableError,
    BankApiClient,
    OverviewError,
    RetryPolicy,
)

pytestmark = pytest.mark.asyncio
FAST_RETRY = RetryPolicy(attempts=3, backoff=0.01)


def account_json(account_id: int) -> dict[str, object]:
    return {
        "id": account_id,
        "number": f"UA-{1000 + account_id}",
        "client_id": 1,
        "currency": "UAH",
        "balance": "10.00",
        "account_type": "current",
    }


def fake_bank(
    *,
    latency: float = 0.0,
    fail_first: int = 0,
    status: int = 503,
    stats: dict[str, int] | None = None,
) -> httpx.MockTransport:
    """Mock зовнішнього HTTP-сервісу: затримка, перші fail_first відповідей - помилка."""
    counters = stats if stats is not None else {}
    counters.update(calls=0, in_flight=0, max_in_flight=0)

    async def handler(request: httpx.Request) -> httpx.Response:
        counters["calls"] += 1
        counters["in_flight"] += 1
        counters["max_in_flight"] = max(counters["max_in_flight"], counters["in_flight"])
        try:
            await asyncio.sleep(latency)
            if counters["calls"] <= fail_first:
                return httpx.Response(status, json={"detail": "temporary"})
            account_id = int(request.url.path.split("/")[2])
            if request.url.path.endswith("/transactions"):
                return httpx.Response(200, json=[{"operation": "deposit"}])
            return httpx.Response(200, json=account_json(account_id))
        finally:
            counters["in_flight"] -= 1

    return httpx.MockTransport(handler)


async def test_overviews_through_real_app(api: BankApiClient, bank: dict[str, int]) -> None:
    ids = [bank["UA-1001"], bank["UA-1002"], bank["UA-2001"], 999]
    results = await api.overviews(ids)
    assert [r.number for r in results if isinstance(r, AccountOverview)] == [
        "UA-1001",
        "UA-1002",
        "UA-2001",
    ]
    assert results[2].balance.currency == "USD"  # type: ignore[union-attr]
    assert results[3] == OverviewError(999, "HTTP 404: рахунок з id=999 не знайдено")
    assert 7 <= api.requests_sent <= 8


async def test_semaphore_limits_concurrent_requests() -> None:
    stats: dict[str, int] = {}
    async with BankApiClient(
        transport=fake_bank(latency=0.02, stats=stats), max_concurrency=3
    ) as api:
        results = await api.overviews(list(range(1, 11)))
    assert all(isinstance(r, AccountOverview) for r in results)
    assert stats["calls"] == 20
    assert stats["max_in_flight"] == 3


async def test_retry_with_backoff_recovers_from_503() -> None:
    stats: dict[str, int] = {}
    async with BankApiClient(
        transport=fake_bank(fail_first=2, stats=stats), retry=FAST_RETRY
    ) as api:
        started = time.perf_counter()
        account = await api.get_json("/accounts/1")
    assert account["number"] == "UA-1001"
    assert stats["calls"] == 3
    assert time.perf_counter() - started >= 0.01 + 0.02


async def test_retry_gives_up_after_all_attempts() -> None:
    async with BankApiClient(transport=fake_bank(fail_first=99), retry=FAST_RETRY) as api:
        with pytest.raises(ApiUnavailableError, match="HTTP 503 після 3 спроб"):
            await api.get_json("/accounts/1")
        assert api.requests_sent == 3


async def test_client_errors_are_not_retried() -> None:
    async with BankApiClient(
        transport=fake_bank(fail_first=99, status=404), retry=FAST_RETRY
    ) as api:
        with pytest.raises(httpx.HTTPStatusError):
            await api.get_json("/accounts/1")
        assert api.requests_sent == 1


async def test_connection_error_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=account_json(1))

    async with BankApiClient(transport=httpx.MockTransport(handler), retry=FAST_RETRY) as api:
        assert (await api.get_json("/accounts/1"))["id"] == 1
    assert calls == 2


async def test_deadline_cancels_unfinished_tasks() -> None:
    async with BankApiClient(transport=fake_bank(latency=5)) as api:
        started = time.perf_counter()
        with pytest.raises(TimeoutError):
            await api.overviews([1, 2, 3], deadline=0.2)
    assert time.perf_counter() - started < 1
    leftovers = [t for t in asyncio.all_tasks() if t.get_name().startswith("account-")]
    assert leftovers == []


async def test_request_timeout_on_real_server(serve: Callable[[FastAPI], str]) -> None:
    slow = FastAPI()

    @slow.get("/accounts/{account_id}")
    async def slow_account(account_id: int) -> dict[str, object]:
        await asyncio.sleep(2)
        return account_json(account_id)

    base_url = serve(slow)
    retry = RetryPolicy(attempts=2, backoff=0.05)
    async with BankApiClient(base_url, timeout=0.2, retry=retry) as api:
        started = time.perf_counter()
        with pytest.raises(ApiUnavailableError, match="ReadTimeout після 2 спроб"):
            await api.get_json("/accounts/1")
    assert 0.4 <= time.perf_counter() - started < 1.5


async def test_end_to_end_over_tcp(
    serve: Callable[[FastAPI], str], settings: Settings, bank: dict[str, int]
) -> None:
    base_url = serve(create_app(settings))
    async with BankApiClient(base_url, max_concurrency=2) as api:
        results = await api.overviews([bank["UA-1001"], bank["UA-1002"]])
    overviews = [r for r in results if isinstance(r, AccountOverview)]
    assert [(r.number, r.balance.amount) for r in overviews] == [
        ("UA-1001", Decimal("1000.00")),
        ("UA-1002", Decimal("250.00")),
    ]
