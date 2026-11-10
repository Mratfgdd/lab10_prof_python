"""Кеш статистики груп (оптимізація після ЛР9) та його інвалідація."""

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from student_manager.caching import StatisticsCache
from student_manager.exceptions import StudentNotFoundError
from student_manager.repositories import GroupStats
from student_manager.services import StudentService


def stats(group_id: int, students: int = 1) -> GroupStats:
    return GroupStats(group_id, f"G-{group_id}", students, 80.0, 90.0, 70.0)


def test_second_request_comes_from_the_cache() -> None:
    cache = StatisticsCache()
    calls: list[int] = []

    def compute() -> GroupStats:
        calls.append(1)
        return stats(1)

    first = cache.get_or_compute(1, compute)
    second = cache.get_or_compute(1, compute)
    assert second is first
    assert (len(calls), cache.hits, cache.misses, len(cache)) == (1, 1, 1, 1)


def test_groups_are_cached_independently() -> None:
    cache = StatisticsCache()
    cache.get_or_compute(1, lambda: stats(1))
    cache.get_or_compute(2, lambda: stats(2))
    assert len(cache) == 2
    assert cache.get_or_compute(2, lambda: stats(2, 99)).students == 1


def test_invalidate_drops_every_entry() -> None:
    cache = StatisticsCache()
    cache.get_or_compute(1, lambda: stats(1))
    cache.invalidate()
    assert len(cache) == 0
    assert cache.get_or_compute(1, lambda: stats(1, 5)).students == 5


def test_value_computed_before_invalidation_is_not_stored() -> None:
    cache = StatisticsCache()

    def compute() -> GroupStats:
        cache.invalidate()
        return stats(1, 7)

    assert cache.get_or_compute(1, compute).students == 7
    assert len(cache) == 0
    assert cache.get_or_compute(1, lambda: stats(1, 8)).students == 8


def test_failed_computation_is_not_cached() -> None:
    cache = StatisticsCache()

    def broken() -> GroupStats:
        raise RuntimeError("база недоступна")

    with pytest.raises(RuntimeError):
        cache.get_or_compute(1, broken)
    assert len(cache) == 0
    assert cache.misses == 1


@pytest.fixture
def cached(
    session_factory: sessionmaker[Session],
) -> tuple[StudentService, StatisticsCache]:
    cache = StatisticsCache()
    with session_factory() as session:
        service = StudentService(session, cache)
        service.create_group("PI-21")
        service.create_group("PI-22")
        service.add_student("Олена", "Коваленко", "PI-21", 90.0)
        service.add_student("Андрій", "Мельник", "PI-21", 70.0)
    return service, cache


def test_service_serves_repeated_statistics_from_the_cache(
    cached: tuple[StudentService, StatisticsCache],
) -> None:
    service, cache = cached
    first = service.group_statistics(1)
    again = service.group_statistics(1)
    assert again is first
    assert cache.hits == 1
    assert first.average == pytest.approx(80.0)


def test_adding_a_student_invalidates_the_cache(
    cached: tuple[StudentService, StatisticsCache],
) -> None:
    service, _ = cached
    assert service.group_statistics(1).students == 2
    service.add_student("Тарас", "Гриценко", "PI-21", 50.0)
    fresh = service.group_statistics(1)
    assert (fresh.students, fresh.worst) == (3, 50.0)


def test_changing_a_grade_invalidates_the_cache(
    cached: tuple[StudentService, StatisticsCache],
) -> None:
    service, _ = cached
    assert service.group_statistics(1).best == pytest.approx(90.0)
    service.update_grade(1, 100.0)
    assert service.group_statistics(1).best == pytest.approx(100.0)


def test_deleting_a_student_invalidates_the_cache(
    cached: tuple[StudentService, StatisticsCache],
) -> None:
    service, _ = cached
    service.group_statistics(1)
    service.delete_student(2)
    assert service.group_statistics(1).students == 1


def test_transfer_invalidates_both_groups(
    cached: tuple[StudentService, StatisticsCache],
) -> None:
    service, _ = cached
    service.group_statistics(1)
    service.group_statistics(2)
    service.transfer_students([2], "PI-22")
    assert service.group_statistics(1).students == 1
    assert service.group_statistics(2).students == 1


def test_failed_write_keeps_the_cache(
    cached: tuple[StudentService, StatisticsCache],
) -> None:
    service, cache = cached
    first = service.group_statistics(1)
    with pytest.raises(StudentNotFoundError, match="не знайдено"):
        service.update_grade(999, 50.0)
    assert service.group_statistics(1) is first
    assert cache.hits == 1


def test_service_without_cache_still_works(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = StudentService(session)
        service.create_group("PI-21")
        assert service.group_statistics(1).students == 0
        service.add_student("Олена", "Коваленко", "PI-21", 90.0)
        assert service.group_statistics(1).students == 1


@pytest.mark.asyncio
async def test_api_statistics_are_fresh_after_a_change(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    group = campus["PI-21"]
    before = (await client.get(f"/groups/{group}/statistics")).json()
    again = (await client.get(f"/groups/{group}/statistics")).json()
    assert again == before
    await client.patch(
        f"/students/{campus['Мельник']}", json={"average_grade": 10}
    )
    after = (await client.get(f"/groups/{group}/statistics")).json()
    assert after["worst_grade"] == pytest.approx(10.0)
    assert after != before
