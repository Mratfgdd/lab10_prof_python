"""Repository Pattern: доступ до даних через SQLAlchemy ORM."""

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from sqlalchemy import ColumnElement, func, inspect, select
from sqlalchemy.orm import Session

from student_manager.models import Base, Group, Student

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """Узагальнений репозиторій: CRUD, спільний для всіх моделей."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        """Зберігає сесію; commit виконує сервіс."""
        self.session = session

    def add(self, entity: ModelT) -> ModelT:
        """Додає сутність і виконує flush, щоб з'явився id."""
        self.session.add(entity)
        self.session.flush()
        return entity

    def get_by_id(self, entity_id: int) -> ModelT | None:
        """Повертає сутність за первинним ключем або None."""
        return self.session.get(self.model, entity_id)

    def get_all(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        """Сторінка сутностей у порядку первинного ключа."""
        statement = (
            select(self.model)
            .order_by(*inspect(self.model).primary_key)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement))

    def count(self) -> int:
        """Кількість записів у таблиці."""
        return (
            self.session.scalar(select(func.count()).select_from(self.model))
            or 0
        )

    def delete(self, entity_id: int) -> bool:
        """Видаляє сутність за id; False, якщо її немає."""
        entity = self.get_by_id(entity_id)
        if entity is None:
            return False
        self.session.delete(entity)
        self.session.flush()
        return True


@dataclass(frozen=True, slots=True)
class GroupStats:
    """Статистика групи: кількість студентів і бали."""

    group_id: int
    name: str
    students: int
    average: float | None
    best: float | None
    worst: float | None


class GroupRepository(Repository[Group]):
    """Репозиторій груп."""

    model = Group

    def create(self, name: str) -> Group:
        """Створює групу з назвою name."""
        return self.add(Group(name=name))

    def get_by_name(self, name: str) -> Group | None:
        """Група за назвою або None."""
        return self.session.scalar(select(Group).where(Group.name == name))

    def _stats(self, *conditions: ColumnElement[bool]) -> list[GroupStats]:
        """Статистика груп (JOIN + GROUP BY) за умовами."""
        statement = (
            select(
                Group.id,
                Group.name,
                func.count(Student.id),
                func.avg(Student.average_grade),
                func.max(Student.average_grade),
                func.min(Student.average_grade),
            )
            .outerjoin(Student, Student.group_id == Group.id)
            .where(*conditions)
            .group_by(Group.id, Group.name)
            .order_by(Group.name)
        )
        return [
            GroupStats(
                group_id,
                name,
                int(students),
                None if average is None else float(average),
                None if best is None else float(best),
                None if worst is None else float(worst),
            )
            for row in self.session.execute(statement)
            for group_id, name, students, average, best, worst in [row]
        ]

    def stats(self) -> list[GroupStats]:
        """Статистика всіх груп, включно з порожніми."""
        return self._stats()

    def stats_of(self, group_id: int) -> GroupStats | None:
        """Статистика однієї групи або None."""
        found = self._stats(Group.id == group_id)
        return found[0] if found else None


class StudentRepository(Repository[Student]):
    """Репозиторій студентів."""

    model = Student

    def find_by_last_name(self, last_name: str) -> list[Student]:
        """Студенти з точним збігом прізвища."""
        statement = (
            select(Student)
            .where(Student.last_name == last_name.strip())
            .order_by(Student.first_name, Student.id)
        )
        return list(self.session.scalars(statement))

    def find_by_group(self, group_id: int) -> list[Student]:
        """Студенти групи за id."""
        statement = (
            select(Student)
            .where(Student.group_id == group_id)
            .order_by(Student.last_name, Student.first_name, Student.id)
        )
        return list(self.session.scalars(statement))

    def filter_by_group(self, group_name: str) -> list[Student]:
        """Студенти групи за назвою (JOIN)."""
        statement = (
            select(Student)
            .join(Group, Student.group_id == Group.id)
            .where(Group.name == group_name)
            .order_by(Student.last_name, Student.first_name, Student.id)
        )
        return list(self.session.scalars(statement))

    @staticmethod
    def _conditions(
        group_id: int | None,
        last_name_prefix: str | None,
        min_grade: float | None,
        max_grade: float | None,
    ) -> list[ColumnElement[bool]]:
        """Умови пошуку: група, префікс прізвища, бали."""
        conditions: list[ColumnElement[bool]] = []
        if group_id is not None:
            conditions.append(Student.group_id == group_id)
        if last_name_prefix is not None:
            prefix = last_name_prefix.strip().casefold()
            conditions.append(
                func.casefold(Student.last_name).startswith(
                    prefix, autoescape=True
                )
            )
        if min_grade is not None:
            conditions.append(Student.average_grade >= min_grade)
        if max_grade is not None:
            conditions.append(Student.average_grade <= max_grade)
        return conditions

    def search(
        self,
        *,
        group_id: int | None = None,
        last_name_prefix: str | None = None,
        min_grade: float | None = None,
        max_grade: float | None = None,
        order_by: Literal["last_name", "average_grade"] = "last_name",
        descending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Student]:
        """Пошук із фільтрами, сортуванням і пагінацією."""
        conditions = self._conditions(
            group_id, last_name_prefix, min_grade, max_grade
        )
        column = (
            Student.average_grade
            if order_by == "average_grade"
            else Student.last_name
        )
        ordering = (column.desc() if descending else column.asc(), Student.id)
        statement = select(Student).where(*conditions).order_by(*ordering)
        return list(
            self.session.scalars(statement.limit(limit).offset(offset))
        )

    def count_matching(
        self,
        *,
        group_id: int | None = None,
        last_name_prefix: str | None = None,
        min_grade: float | None = None,
        max_grade: float | None = None,
    ) -> int:
        """Кількість студентів за фільтрами без пагінації."""
        conditions = self._conditions(
            group_id, last_name_prefix, min_grade, max_grade
        )
        statement = (
            select(func.count()).select_from(Student).where(*conditions)
        )
        return self.session.scalar(statement) or 0

    def update_grade(self, student_id: int, grade: float) -> Student | None:
        """Змінює середній бал; None, якщо студента немає."""
        student = self.get_by_id(student_id)
        if student is None:
            return None
        student.average_grade = grade
        self.session.flush()
        return student

    def best(self) -> Student | None:
        """Студент із найбільшим середнім балом."""
        statement = (
            select(Student)
            .order_by(
                Student.average_grade.desc(), Student.last_name, Student.id
            )
            .limit(1)
        )
        return self.session.scalar(statement)

    def group_average(self, group_id: int) -> float | None:
        """Середній бал групи (AVG) або None для порожньої."""
        result = self.session.scalar(
            select(func.avg(Student.average_grade)).where(
                Student.group_id == group_id
            )
        )
        return None if result is None else float(result)
