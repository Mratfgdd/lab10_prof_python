"""Pydantic-схеми запитів і відповідей REST API."""

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from student_manager.models import Student
from student_manager.repositories import GroupStats
from student_manager.validation import EMAIL_PATTERN, GROUP_PATTERN

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)
]
Grade = Annotated[float, Field(ge=0, le=100)]
PositiveId = Annotated[int, Field(gt=0)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=255,
        pattern=f"^{EMAIL_PATTERN.pattern}$",
    ),
]
GroupName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, pattern=f"^{GROUP_PATTERN.pattern}$"
    ),
]
NON_NULLABLE = ("first_name", "last_name", "group_id", "average_grade")


class StudentCreate(BaseModel):
    """Тіло POST /students."""

    model_config = ConfigDict(extra="forbid")

    first_name: Name
    last_name: Name
    group_id: PositiveId
    average_grade: Grade
    email: Email | None = None


class StudentUpdate(BaseModel):
    """Тіло PATCH /students/{id}: змінюються лише передані поля."""

    model_config = ConfigDict(extra="forbid")

    first_name: Name | None = None
    last_name: Name | None = None
    group_id: PositiveId | None = None
    average_grade: Grade | None = None
    email: Email | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> Self:
        """Вимагає хоча б одне поле; null лише для email."""
        if not self.model_fields_set:
            raise ValueError("потрібно вказати хоча б одне поле для оновлення")
        for field in NON_NULLABLE:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"поле {field} не може бути null")
        return self


class StudentOut(BaseModel):
    """Студент у відповіді API."""

    id: int
    first_name: str
    last_name: str
    group_id: int
    group_name: str
    average_grade: float
    email: str | None

    @classmethod
    def from_student(cls, student: Student) -> Self:
        """Будує відповідь з ORM-об'єкта."""
        return cls(
            id=student.id,
            first_name=student.first_name,
            last_name=student.last_name,
            group_id=student.group_id,
            group_name=student.group.name,
            average_grade=student.average_grade,
            email=student.email,
        )


class GroupCreate(BaseModel):
    """Тіло POST /groups."""

    model_config = ConfigDict(extra="forbid")

    name: GroupName


class GroupStatisticsOut(BaseModel):
    """Статистика групи у відповіді API."""

    group_id: int
    name: str
    students_count: int
    average_grade: float | None
    best_grade: float | None
    worst_grade: float | None

    @classmethod
    def from_stats(cls, stats: GroupStats) -> Self:
        """Будує відповідь зі статистики репозиторію."""
        return cls(
            group_id=stats.group_id,
            name=stats.name,
            students_count=stats.students,
            average_grade=None
            if stats.average is None
            else round(stats.average, 2),
            best_grade=stats.best,
            worst_grade=stats.worst,
        )


class TransferIn(BaseModel):
    """Тіло запиту на масове переведення студентів."""

    model_config = ConfigDict(extra="forbid")

    student_ids: Annotated[
        list[PositiveId], Field(min_length=1, max_length=500)
    ]


class TransferOut(BaseModel):
    """Результат переведення."""

    group_id: int
    moved: int


class BatchStatisticsIn(BaseModel):
    """Тіло запиту пакетної статистики груп."""

    model_config = ConfigDict(extra="forbid")

    group_ids: Annotated[list[PositiveId], Field(min_length=1, max_length=50)]


class HealthOut(BaseModel):
    """Стан сервісу для health-перевірок (Docker, оркестратор)."""

    status: str
    environment: str
    version: str
    database: str


class ErrorOut(BaseModel):
    """Структурована помилка: код і опис."""

    error: str
    detail: str
