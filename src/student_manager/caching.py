"""Кеш статистики груп із версіями (оптимізація, що лишилась після ЛР9).

Повторний запит статистики групи віддається з пам'яті. Будь-яка зміна даних
збільшує версії й скидає записи; значення, обчислене до зміни, у кеш не
потрапляє (захист від гонки між читачем і записувачем).
"""

import threading
from collections.abc import Callable

from student_manager.repositories import GroupStats


class StatisticsCache:
    """Потокобезпечний кеш GroupStats за id групи."""

    def __init__(self) -> None:
        """Створює порожній кеш."""
        self._lock = threading.Lock()
        self._items: dict[int, GroupStats] = {}
        self._version = 0
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        """Кількість груп у кеші."""
        with self._lock:
            return len(self._items)

    def get_or_compute(
        self, group_id: int, compute: Callable[[], GroupStats]
    ) -> GroupStats:
        """Повертає статистику з кешу або обчислює її й запам'ятовує."""
        with self._lock:
            cached = self._items.get(group_id)
            if cached is not None:
                self.hits += 1
                return cached
            self.misses += 1
            version = self._version
        stats = compute()
        with self._lock:
            if version == self._version:
                self._items[group_id] = stats
        return stats

    def invalidate(self) -> None:
        """Скидає всі записи після зміни даних."""
        with self._lock:
            self._version += 1
            self._items.clear()
