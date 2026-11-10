"""Винятки предметної області."""


class StudentManagerError(Exception):
    """Базовий виняток застосунку."""


class StudentValidationError(StudentManagerError, ValueError):
    """Некоректні дані студента, групи або запиту."""


class StudentNotFoundError(StudentManagerError, ValueError):
    """Студента не знайдено."""


class GroupNotFoundError(StudentManagerError, ValueError):
    """Групу не знайдено."""


class DuplicateGroupError(StudentManagerError):
    """Група з такою назвою вже існує."""


class DuplicateEmailError(StudentManagerError):
    """Адреса електронної пошти вже використовується."""


class GroupNotEmptyError(StudentManagerError):
    """Групу зі студентами не можна видалити без force."""


class SchemaMissingError(StudentManagerError):
    """Схему БД не створено: потрібен alembic upgrade head."""


class UnauthorizedError(StudentManagerError):
    """Відсутній або хибний API-ключ у заголовку X-API-Key."""


class BatchTimeoutError(StudentManagerError):
    """Пакетна операція не вклалась у відведений час."""
