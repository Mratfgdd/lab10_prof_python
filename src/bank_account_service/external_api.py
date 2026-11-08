"""Асинхронний HTTP-клієнт Bank API: огляд балансів та історії кількох рахунків.

asyncio.Task + gather - запити виконуються паралельно; Semaphore - не більше N запитів
одночасно; timeout - на кожен запит (httpx) і на всю операцію (asyncio.wait_for);
retry з exponential backoff - для тимчасових збоїв (обрив, timeout, 429/5xx).

Запуск: bank-api-client overview 1 2 3 [--base-url URL] [--concurrency N]
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Self

import httpx

from bank_account_service.value_objects import Money

DEFAULT_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    backoff: float = 0.25
    statuses: frozenset[int] = field(default=frozenset({429, 500, 502, 503, 504}))

    def delay(self, attempt: int) -> float:
        return self.backoff * 2.0 ** (attempt - 1)


class ApiUnavailableError(Exception):
    """Сервіс не відповів успішно після всіх спроб."""


@dataclass(frozen=True, slots=True)
class AccountOverview:
    account_id: int
    number: str
    balance: Money
    operations: int
    last_operation: str | None


@dataclass(frozen=True, slots=True)
class OverviewError:
    account_id: int
    reason: str


class BankApiClient:
    """Один httpx.AsyncClient (пул з'єднань) на весь час роботи: async with BankApiClient()."""

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        timeout: float = 5.0,
        max_concurrency: int = 5,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retry = retry or RetryPolicy()
        self.requests_sent = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._client.aclose()

    async def get_json(self, path: str) -> Any:
        """GET із retry: повторюються лише тимчасові збої; 4xx піднімає HTTPStatusError одразу."""
        reason = ""
        for attempt in range(1, self._retry.attempts + 1):
            try:
                async with self._semaphore:
                    self.requests_sent += 1
                    response = await self._client.get(path)
                if response.status_code not in self._retry.statuses:
                    response.raise_for_status()
                    return response.json()
                reason = f"HTTP {response.status_code}"
            except httpx.TransportError as error:
                reason = type(error).__name__
            if attempt < self._retry.attempts:
                await asyncio.sleep(self._retry.delay(attempt))
        raise ApiUnavailableError(f"GET {path}: {reason} після {self._retry.attempts} спроб")

    async def account_overview(self, account_id: int) -> AccountOverview:
        try:
            async with asyncio.TaskGroup() as group:
                account_task = group.create_task(self.get_json(f"/accounts/{account_id}"))
                history_task = group.create_task(
                    self.get_json(f"/accounts/{account_id}/transactions")
                )
        except ExceptionGroup as errors:
            raise errors.exceptions[0] from None
        account, history = account_task.result(), history_task.result()
        return AccountOverview(
            account_id=account_id,
            number=account["number"],
            balance=Money(Decimal(account["balance"]), account["currency"]),
            operations=len(history),
            last_operation=history[-1]["operation"] if history else None,
        )

    async def overviews(
        self, account_ids: Sequence[int], *, deadline: float = 10.0
    ) -> list[AccountOverview | OverviewError]:
        """Огляд кількох рахунків: Task на кожен рахунок, gather, загальний timeout."""
        tasks = [
            asyncio.create_task(self.account_overview(i), name=f"account-{i}") for i in account_ids
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=deadline
        )
        return [
            result
            if isinstance(result, AccountOverview)
            else OverviewError(account_id, describe(result))
            for account_id, result in zip(account_ids, results, strict=True)
        ]


def describe(error: BaseException) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        try:
            detail = error.response.json().get("detail", "")
        except ValueError:
            detail = error.response.reason_phrase
        return f"HTTP {error.response.status_code}: {detail}"
    return f"{type(error).__name__}: {error}"


def accounts_word(number: int) -> str:
    if number % 10 == 1 and number % 100 != 11:
        return "рахунок"
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return "рахунки"
    return "рахунків"


async def run_overview(args: argparse.Namespace) -> int:
    retry = RetryPolicy(attempts=args.retries)
    started = time.perf_counter()
    async with BankApiClient(
        args.base_url, timeout=args.timeout, retry=retry, max_concurrency=args.concurrency
    ) as client:
        try:
            results = await client.overviews(args.ids, deadline=args.deadline)
        except TimeoutError:
            print(f"Помилка: огляд не завершився за {args.deadline} с", file=sys.stderr)
            return 1
        sent = client.requests_sent
    count = len(args.ids)
    print(
        f"{args.base_url}: {count} {accounts_word(count)}, "
        f"одночасно не більше {args.concurrency} запитів"
    )
    print(f"{'id':>4}  {'Номер':<9} {'Баланс':>16}  Операцій  Остання")
    for item in results:
        if isinstance(item, AccountOverview):
            print(
                f"{item.account_id:>4}  {item.number:<9} {item.balance!s:>16}  "
                f"{item.operations:>8}  {item.last_operation or '-'}"
            )
        else:
            print(f"{item.account_id:>4}  помилка: {item.reason}")
    print(f"HTTP-запитів: {sent}, час: {time.perf_counter() - started:.2f} с")
    return 0 if all(isinstance(item, AccountOverview) for item in results) else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bank-api-client", description="Клієнт Bank API")
    commands = parser.add_subparsers(dest="command", required=True)
    overview = commands.add_parser("overview", help="баланси та історія кількох рахунків")
    overview.add_argument("ids", type=int, nargs="+")
    overview.add_argument("--base-url", default=DEFAULT_URL)
    overview.add_argument("--concurrency", type=int, default=3)
    overview.add_argument("--timeout", type=float, default=5.0, help="timeout запиту, с")
    overview.add_argument("--deadline", type=float, default=10.0, help="timeout операції, с")
    overview.add_argument("--retries", type=int, default=3)
    return asyncio.run(run_overview(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
