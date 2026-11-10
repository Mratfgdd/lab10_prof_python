"""Пошук студентів групи через стандартний DB-API (sqlite3)."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

FIND_BY_GROUP = """
    SELECT s.id, s.last_name, s.first_name, g.name, s.average_grade, s.email
    FROM students AS s
    JOIN groups AS g ON g.id = s.group_id
    WHERE g.name = ?
    ORDER BY s.last_name, s.first_name, s.id
"""


@dataclass(frozen=True, slots=True)
class StudentRow:
    """Рядок результату пошуку."""

    student_id: int
    last_name: str
    first_name: str
    group: str
    average_grade: float
    email: str | None


def find_students_by_group(
    database: Path | str, group_name: str
) -> list[StudentRow]:
    """Параметризований пошук студентів за назвою групи."""
    with closing(sqlite3.connect(database)) as connection:
        cursor = connection.cursor()
        cursor.execute(FIND_BY_GROUP, (group_name,))
        rows = cursor.fetchall()
        cursor.close()
    return [StudentRow(*row) for row in rows]
