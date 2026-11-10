"""Шар сервісів: бізнес-логіка й транзакції поверх репозиторіїв."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from student_manager.caching import StatisticsCache
from student_manager.exceptions import (
    DuplicateEmailError,
    DuplicateGroupError,
    GroupNotEmptyError,
    GroupNotFoundError,
    StudentNotFoundError,
    StudentValidationError,
)
from student_manager.models import Group, Student
from student_manager.repositories import (
    GroupRepository,
    GroupStats,
    StudentRepository,
)
from student_manager.validation import clean_email, clean_group_name

UPDATABLE_FIELDS = frozenset(
    {"first_name", "last_name", "average_grade", "email", "group_id"}
)


def transfer_students(
    session: Session, student_ids: Sequence[int], new_group_id: int
) -> int:
    """Переводить студентів до групи однією транзакцією."""
    unique_ids = list(dict.fromkeys(student_ids))
    try:
        if not unique_ids:
            raise StudentValidationError(
                "список студентів для переведення порожній"
            )
        group = session.get(Group, new_group_id)
        if group is None:
            raise GroupNotFoundError(f"групу з id={new_group_id} не знайдено")
        for student_id in unique_ids:
            student = session.get(Student, student_id)
            if student is None:
                raise StudentNotFoundError(
                    f"студента з id={student_id} не знайдено"
                )
            student.group = group
            session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return len(unique_ids)


class StudentService:
    """Сервіс: кожна змінна операція виконується в одній транзакції."""

    def __init__(
        self, session: Session, cache: StatisticsCache | None = None
    ) -> None:
        """Створює репозиторії поверх сесії; cache - необов'язковий."""
        self.session = session
        self.cache = cache
        self.groups = GroupRepository(session)
        self.students = StudentRepository(session)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Commit при успіху, rollback при будь-якій помилці."""
        try:
            yield
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self._changed()

    def _changed(self) -> None:
        """Дані змінилися: застаріла статистика груп скидається."""
        if self.cache is not None:
            self.cache.invalidate()

    def _group(self, name: str) -> Group:
        """Група за назвою або GroupNotFoundError."""
        group = self.groups.get_by_name(clean_group_name(name))
        if group is None:
            raise GroupNotFoundError(f"групу {name} не знайдено")
        return group

    def _student(self, student_id: int) -> Student:
        """Студент за id або StudentNotFoundError."""
        student = self.students.get_by_id(student_id)
        if student is None:
            raise StudentNotFoundError(
                f"студента з id={student_id} не знайдено"
            )
        return student

    def create_group(self, name: str) -> Group:
        """Створює групу; дубль назви дає DuplicateGroupError."""
        with self._transaction():
            try:
                return self.groups.create(name)
            except IntegrityError as error:
                if "groups.name" not in str(error.orig):
                    raise
                raise DuplicateGroupError(f"група {name} уже існує") from error

    def _group_by_id(self, group_id: int) -> Group:
        """Група за id або GroupNotFoundError."""
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise GroupNotFoundError(f"групу з id={group_id} не знайдено")
        return group

    def _insert_student(
        self,
        first_name: str,
        last_name: str,
        group: Group,
        average_grade: float,
        email: str | None,
    ) -> Student:
        """Додає студента; дубль email дає DuplicateEmailError."""
        student = Student(
            first_name=first_name,
            last_name=last_name,
            average_grade=average_grade,
            email=email,
            group=group,
        )
        try:
            self.students.add(student)
        except IntegrityError as error:
            if "students.email" not in str(error.orig):
                raise
            raise DuplicateEmailError(
                f"адреса {student.email} уже використовується"
            ) from error
        return student

    def add_student(
        self,
        first_name: str,
        last_name: str,
        group_name: str,
        average_grade: float,
        email: str | None = None,
    ) -> Student:
        """Додає студента до групи за назвою."""
        with self._transaction():
            group = self._group(group_name)
            return self._insert_student(
                first_name, last_name, group, average_grade, email
            )

    def create_student(
        self,
        first_name: str,
        last_name: str,
        group_id: int,
        average_grade: float,
        email: str | None = None,
    ) -> Student:
        """Додає студента до групи за id."""
        with self._transaction():
            group = self._group_by_id(group_id)
            return self._insert_student(
                first_name, last_name, group, average_grade, email
            )

    def update_student(
        self, student_id: int, changes: Mapping[str, Any]
    ) -> Student:
        """Змінює кілька полів студента однією транзакцією."""
        unknown = set(changes) - UPDATABLE_FIELDS
        if unknown:
            raise StudentValidationError(
                f"поля {sorted(unknown)} змінювати не можна"
            )
        with self._transaction():
            student = self._student(student_id)
            if "group_id" in changes:
                student.group = self._group_by_id(changes["group_id"])
            for field in UPDATABLE_FIELDS - {"group_id"}:
                if field in changes:
                    setattr(student, field, changes[field])
            try:
                self.session.flush()
            except IntegrityError as error:
                if "students.email" not in str(error.orig):
                    raise
                address = changes.get("email")
                raise DuplicateEmailError(
                    f"адреса {address} уже використовується"
                ) from error
        return student

    def get_student(self, student_id: int) -> Student:
        """Студент за id."""
        return self._student(student_id)

    def get_group(self, group_id: int) -> Group:
        """Група за id."""
        return self._group_by_id(group_id)

    def group_statistics(self, group_id: int) -> GroupStats:
        """Статистика групи за id; повторні запити беруться з кешу."""
        if self.cache is None:
            return self._load_statistics(group_id)
        return self.cache.get_or_compute(
            group_id, lambda: self._load_statistics(group_id)
        )

    def _load_statistics(self, group_id: int) -> GroupStats:
        """Статистика групи з бази даних."""
        stats = self.groups.stats_of(group_id)
        if stats is None:
            raise GroupNotFoundError(f"групу з id={group_id} не знайдено")
        return stats

    def students_of_group(self, group_id: int) -> list[Student]:
        """Студенти групи за id."""
        self._group_by_id(group_id)
        return self.students.find_by_group(group_id)

    def find_by_last_name(self, last_name: str) -> list[Student]:
        """Точний пошук за прізвищем."""
        return self.students.find_by_last_name(last_name)

    def filter_by_group(self, group_name: str) -> list[Student]:
        """Студенти групи за назвою."""
        return self.students.filter_by_group(self._group(group_name).name)

    def _resolve_group(
        self,
        group_name: str | None,
        group_id: int | None,
        min_grade: float | None,
        max_grade: float | None,
    ) -> int | None:
        """Перевіряє діапазон балів і визначає id групи."""
        if (
            min_grade is not None
            and max_grade is not None
            and min_grade > max_grade
        ):
            raise StudentValidationError("min_grade більший за max_grade")
        if group_name is not None:
            return self._group(group_name).id
        if group_id is not None:
            return self._group_by_id(group_id).id
        return None

    def list_students(
        self,
        *,
        group_name: str | None = None,
        group_id: int | None = None,
        last_name_prefix: str | None = None,
        min_grade: float | None = None,
        max_grade: float | None = None,
        order_by: Literal["last_name", "average_grade"] = "last_name",
        descending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Student]:
        """Студенти за фільтрами з сортуванням і пагінацією."""
        resolved = self._resolve_group(
            group_name, group_id, min_grade, max_grade
        )
        return self.students.search(
            group_id=resolved,
            last_name_prefix=last_name_prefix,
            min_grade=min_grade,
            max_grade=max_grade,
            order_by=order_by,
            descending=descending,
            limit=limit,
            offset=offset,
        )

    def count_students(
        self,
        *,
        group_name: str | None = None,
        group_id: int | None = None,
        last_name_prefix: str | None = None,
        min_grade: float | None = None,
        max_grade: float | None = None,
    ) -> int:
        """Кількість студентів за тими самими фільтрами."""
        resolved = self._resolve_group(
            group_name, group_id, min_grade, max_grade
        )
        return self.students.count_matching(
            group_id=resolved,
            last_name_prefix=last_name_prefix,
            min_grade=min_grade,
            max_grade=max_grade,
        )

    def get_group_average(self, group_id: int) -> float:
        """Середній бал групи; 0.0 для порожньої."""
        average = self.students.group_average(group_id)
        return 0.0 if average is None else average

    def get_group_average_by_name(self, group_name: str) -> float:
        """Середній бал групи за назвою."""
        return self.get_group_average(self._group(group_name).id)

    def get_best_student(self) -> Student | None:
        """Найкращий студент або None."""
        return self.students.best()

    def group_report(self) -> list[GroupStats]:
        """Статистика всіх груп."""
        return self.groups.stats()

    def update_grade(self, student_id: int, grade: float) -> Student:
        """Змінює середній бал студента."""
        with self._transaction():
            student = self.students.update_grade(student_id, grade)
            if student is None:
                raise StudentNotFoundError(
                    f"студента з id={student_id} не знайдено"
                )
        return student

    def set_email(self, student_id: int, email: str | None) -> Student:
        """Встановлює або очищує адресу електронної пошти."""
        cleaned = clean_email(email)
        with self._transaction():
            student = self._student(student_id)
            student.email = cleaned
            try:
                self.session.flush()
            except IntegrityError as error:
                if "students.email" not in str(error.orig):
                    raise
                raise DuplicateEmailError(
                    f"адреса {cleaned} уже використовується"
                ) from error
        return student

    def transfer_students(
        self, student_ids: Sequence[int], group_name: str
    ) -> int:
        """Переводить студентів до групи за назвою."""
        return self.transfer_to_group(student_ids, self._group(group_name).id)

    def transfer_to_group(
        self, student_ids: Sequence[int], group_id: int
    ) -> int:
        """Переводить студентів до групи за id; скидає кеш статистики."""
        moved = transfer_students(self.session, student_ids, group_id)
        self._changed()
        return moved

    def delete_student(self, student_id: int) -> None:
        """Видаляє студента."""
        with self._transaction():
            if not self.students.delete(student_id):
                raise StudentNotFoundError(
                    f"студента з id={student_id} не знайдено"
                )

    def delete_group(self, name: str, *, force: bool = False) -> int:
        """Видаляє групу; непорожню - лише з force."""
        with self._transaction():
            group = self._group(name)
            members = len(group.students)
            if members and not force:
                raise GroupNotEmptyError(
                    f"у групі {name} є студенти: {members}"
                )
            self.session.delete(group)
            self.session.flush()
        return members
