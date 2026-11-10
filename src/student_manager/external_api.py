"""Асинхронний клієнт REST API на httpx: Task, gather, Semaphore, retry."""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Self

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Політика повторних спроб: кількість, пауза, коди відповідей."""

    attempts: int = 3
    backoff: float = 0.25
    statuses: frozenset[int] = field(
        default=frozenset({429, 500, 502, 503, 504})
    )

    def delay(self, attempt: int) -> float:
        """Пауза перед наступною спробою (експоненційна)."""
        return self.backoff * 2.0 ** (attempt - 1)


class ApiUnavailableError(Exception):
    """Сервіс не відповів успішно після всіх спроб."""


@dataclass(frozen=True, slots=True)
class GroupSummary:
    """Статистика групи, отримана від API."""

    group_id: int
    name: str
    students: int
    average: float | None
    best: float | None
    worst: float | None


@dataclass(frozen=True, slots=True)
class SummaryError:
    """Причина, з якої статистику групи отримати не вдалося."""

    group_id: int
    reason: str


class StudentApiClient:
    """Клієнт API: один httpx.AsyncClient, Semaphore і retry."""

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        timeout: float = 5.0,
        max_concurrency: int = 5,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Створює клієнт; transport дозволяє підставити тестовий."""
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retry = retry or RetryPolicy()
        self.requests_sent = 0

    @property
    def is_closed(self) -> bool:
        """True, коли HTTP-клієнт уже закрито."""
        return self._client.is_closed

    async def __aenter__(self) -> Self:
        """Вхід у асинхронний контекстний менеджер."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Закриває httpx.AsyncClient."""
        await self._client.aclose()

    async def get_json(self, path: str) -> Any:
        """GET із retry для тимчасових збоїв; 4xx піднімається одразу."""
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
        raise ApiUnavailableError(
            f"GET {path}: {reason} після {self._retry.attempts} спроб"
        )

    async def group_summary(self, group_id: int) -> GroupSummary:
        """Статистика однієї групи."""
        data = await self.get_json(f"/groups/{group_id}/statistics")
        return GroupSummary(
            group_id=data["group_id"],
            name=data["name"],
            students=data["students_count"],
            average=data["average_grade"],
            best=data["best_grade"],
            worst=data["worst_grade"],
        )

    async def groups_summary(
        self, group_ids: Sequence[int], *, deadline: float = 10.0
    ) -> list[GroupSummary | SummaryError]:
        """Статистика кількох груп паралельно з timeout."""
        tasks = [
            asyncio.create_task(
                self.group_summary(group_id), name=f"group-{group_id}"
            )
            for group_id in group_ids
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=deadline
        )
        return [
            result
            if isinstance(result, GroupSummary)
            else SummaryError(group_id, describe(result))
            for group_id, result in zip(group_ids, results, strict=True)
        ]


def describe(error: BaseException) -> str:
    """Короткий опис помилки для виведення."""
    if isinstance(error, httpx.HTTPStatusError):
        try:
            detail = error.response.json().get("detail", "")
        except ValueError:
            detail = error.response.reason_phrase
        return f"HTTP {error.response.status_code}: {detail}"
    return f"{type(error).__name__}: {error}"


def groups_word(number: int) -> str:
    """Форма слова «група» для числівника."""
    if number % 10 == 1 and number % 100 != 11:
        return "група"
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return "групи"
    return "груп"


async def run_stats(args: argparse.Namespace) -> int:
    """Виконує команду stats і друкує таблицю."""
    retry = RetryPolicy(attempts=args.retries)
    started = time.perf_counter()
    async with StudentApiClient(
        args.base_url,
        timeout=args.timeout,
        retry=retry,
        max_concurrency=args.concurrency,
    ) as client:
        try:
            results = await client.groups_summary(
                args.ids, deadline=args.deadline
            )
        except TimeoutError:
            print(
                f"Помилка: статистика не отримана за {args.deadline} с",
                file=sys.stderr,
            )
            return 1
        sent = client.requests_sent
    count = len(args.ids)
    print(
        f"{args.base_url}: {count} {groups_word(count)}, "
        f"одночасно не більше {args.concurrency} запитів"
    )
    print(
        f"{'id':>3}  {'Група':<6} {'Студентів':>9} {'Середній':>9} "
        f"{'Макс':>6} "
        f"{'Мін':>6}"
    )
    for item in results:
        if isinstance(item, GroupSummary):
            average = "-" if item.average is None else f"{item.average:.2f}"
            best = "-" if item.best is None else f"{item.best:.2f}"
            worst = "-" if item.worst is None else f"{item.worst:.2f}"
            print(
                f"{item.group_id:>3}  {item.name:<6} {item.students:>9} "
                f"{average:>9} {best:>6} {worst:>6}"
            )
        else:
            print(f"{item.group_id:>3}  помилка: {item.reason}")
    print(f"HTTP-запитів: {sent}, час: {time.perf_counter() - started:.2f} с")
    return 0 if all(isinstance(item, GroupSummary) for item in results) else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входу student-api-client; повертає код виходу."""
    parser = argparse.ArgumentParser(
        prog="student-api-client", description="Клієнт Student API"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    stats = commands.add_parser(
        "stats", help="статистика кількох груп паралельно"
    )
    stats.add_argument("ids", type=int, nargs="+")
    stats.add_argument("--base-url", default=DEFAULT_URL)
    stats.add_argument("--concurrency", type=int, default=3)
    stats.add_argument(
        "--timeout", type=float, default=5.0, help="timeout запиту, с"
    )
    stats.add_argument(
        "--deadline", type=float, default=10.0, help="timeout операції, с"
    )
    stats.add_argument("--retries", type=int, default=3)
    return asyncio.run(run_stats(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
