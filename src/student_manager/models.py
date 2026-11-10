"""ORM-моделі SQLAlchemy: групи й студенти (one-to-many)."""

from sqlalchemy import CheckConstraint, Float, ForeignKey, MetaData, String
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    validates,
)

from student_manager.validation import (
    clean_email,
    clean_grade,
    clean_group_name,
    clean_name,
)

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    """Базовий клас моделей з іменованими обмеженнями для Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Group(Base):
    """Академічна група."""

    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)

    students: Mapped[list["Student"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Student.id",
    )

    @validates("name")
    def _validate_name(self, _key: str, value: object) -> str:
        """Перевіряє формат назви групи."""
        return clean_group_name(value)


class Student(Base):
    """Студент: ім'я, прізвище, середній бал, група, email."""

    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint(
            "average_grade >= 0 AND average_grade <= 100",
            name="grade_in_range",
        ),
        CheckConstraint(
            "length(trim(first_name)) > 0 AND length(trim(last_name)) > 0",
            name="names_not_blank",
        ),
        CheckConstraint(
            "email IS NULL OR email LIKE '%_@_%._%'", name="email_format"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), index=True)
    average_grade: Mapped[float] = mapped_column(Float)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    group: Mapped[Group] = relationship(back_populates="students")

    @validates("first_name")
    def _validate_first_name(self, _key: str, value: object) -> str:
        """Обрізає пробіли й перевіряє ім'я."""
        return clean_name(value, "ім'я")

    @validates("last_name")
    def _validate_last_name(self, _key: str, value: object) -> str:
        """Обрізає пробіли й перевіряє прізвище."""
        return clean_name(value, "прізвище")

    @validates("average_grade")
    def _validate_grade(self, _key: str, value: object) -> float:
        """Перевіряє, що середній бал у межах 0-100."""
        return clean_grade(value)

    @validates("email")
    def _validate_email(self, _key: str, value: object) -> str | None:
        """Нормалізує адресу пошти до нижнього регістру."""
        return clean_email(value)

    @property
    def full_name(self) -> str:
        """Прізвище та ім'я для виведення."""
        return f"{self.last_name} {self.first_name}"
