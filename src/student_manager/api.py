"""REST API системи обліку студентів: endpoints, помилки, create_app()."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Query,
    Request,
    Response,
    status,
)
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from student_manager import __version__
from student_manager.config import Settings, get_settings
from student_manager.dependencies import (
    GroupId,
    ServiceDep,
    StudentId,
    close_runtime,
    get_runtime,
    in_thread,
    require_token,
)
from student_manager.exceptions import (
    BatchTimeoutError,
    DuplicateEmailError,
    DuplicateGroupError,
    GroupNotEmptyError,
    GroupNotFoundError,
    SchemaMissingError,
    StudentManagerError,
    StudentNotFoundError,
    StudentValidationError,
    UnauthorizedError,
)
from student_manager.schemas import (
    BatchStatisticsIn,
    ErrorOut,
    GroupCreate,
    GroupStatisticsOut,
    HealthOut,
    StudentCreate,
    StudentOut,
    StudentUpdate,
    TransferIn,
    TransferOut,
)
from student_manager.services import StudentService

logger = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
WRITE = [Depends(require_token)]
TAGS = [
    {
        "name": "service",
        "description": "Службові endpoints: перевірка стану",
    },
    {
        "name": "students",
        "description": "Студенти: CRUD, пошук, фільтри, найкращий студент",
    },
    {
        "name": "groups",
        "description": "Групи, студенти групи, статистика, переведення",
    },
    {
        "name": "statistics",
        "description": "Статистика кількох груп паралельно",
    },
]
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorOut} for code in (401, 404, 409, 422)
}
STATUS_BY_ERROR: list[tuple[type[StudentManagerError], int]] = [
    (UnauthorizedError, status.HTTP_401_UNAUTHORIZED),
    (StudentNotFoundError, status.HTTP_404_NOT_FOUND),
    (GroupNotFoundError, status.HTTP_404_NOT_FOUND),
    (DuplicateEmailError, status.HTTP_409_CONFLICT),
    (DuplicateGroupError, status.HTTP_409_CONFLICT),
    (GroupNotEmptyError, status.HTTP_409_CONFLICT),
    (StudentValidationError, 422),
    (BatchTimeoutError, status.HTTP_504_GATEWAY_TIMEOUT),
    (SchemaMissingError, status.HTTP_503_SERVICE_UNAVAILABLE),
]

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Відомості про сервіс і адреса документації."""
    return {
        "service": "Student Manager API",
        "version": __version__,
        "docs": "/docs",
    }


def check_database(app: FastAPI) -> str:
    """Перевіряє з'єднання з БД і наявність схеми: ok або unavailable."""
    try:
        runtime = get_runtime(app)
        with runtime.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, StudentManagerError, OSError) as error:
        logger.warning("база даних недоступна: %s", type(error).__name__)
        return "unavailable"
    return "ok"


@router.get(
    "/health",
    tags=["service"],
    response_model=HealthOut,
    responses={503: {"model": HealthOut}},
)
async def health(request: Request) -> JSONResponse:
    """Стан сервісу: версія, середовище та доступність бази даних."""
    settings: Settings = request.app.state.settings
    database = await in_thread(lambda: check_database(request.app))
    healthy = database == "ok"
    body = HealthOut(
        status="ok" if healthy else "unavailable",
        environment=settings.environment,
        version=__version__,
        database=database,
    )
    code = (
        status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=code, content=body.model_dump())


@router.get("/students", tags=["students"], responses=ERRORS)
async def list_students(
    service: ServiceDep,
    response: Response,
    last_name: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Префікс прізвища, без урахування регістру",
        ),
    ] = None,
    group_id: Annotated[int | None, Query(gt=0)] = None,
    min_grade: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_grade: Annotated[float | None, Query(ge=0, le=100)] = None,
    sort: Literal["last_name", "average_grade"] = "last_name",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[StudentOut]:
    """Список студентів: пошук за прізвищем, фільтри, сортування, сторінки.

    Кількість знайдених студентів (без limit) повертається в заголовку
    X-Total-Count.
    """

    def run() -> tuple[list[StudentOut], int]:
        filters: dict[str, Any] = {
            "last_name_prefix": last_name,
            "group_id": group_id,
            "min_grade": min_grade,
            "max_grade": max_grade,
        }
        found = service.list_students(
            **filters,
            order_by=sort,
            descending=order == "desc",
            limit=limit,
            offset=offset,
        )
        total = service.count_students(**filters)
        return [StudentOut.from_student(item) for item in found], total

    students, total = await in_thread(run)
    response.headers["X-Total-Count"] = str(total)
    return students


@router.get("/students/best", tags=["students"], responses=ERRORS)
async def best_student(service: ServiceDep) -> StudentOut:
    """Студент із найбільшим середнім балом."""

    def run() -> StudentOut:
        student = service.get_best_student()
        if student is None:
            raise StudentNotFoundError("студентів ще немає")
        return StudentOut.from_student(student)

    return await in_thread(run)


@router.get("/students/{student_id}", tags=["students"], responses=ERRORS)
async def get_student(
    student_id: StudentId, service: ServiceDep
) -> StudentOut:
    """Студент за id."""
    return await in_thread(
        lambda: StudentOut.from_student(service.get_student(student_id))
    )


@router.post(
    "/students",
    status_code=status.HTTP_201_CREATED,
    tags=["students"],
    responses=ERRORS,
    dependencies=WRITE,
)
async def create_student(
    data: StudentCreate, service: ServiceDep, response: Response
) -> StudentOut:
    """Додає студента; адреса нового ресурсу — в заголовку Location."""
    created = await in_thread(
        lambda: StudentOut.from_student(
            service.create_student(
                data.first_name,
                data.last_name,
                data.group_id,
                data.average_grade,
                data.email,
            )
        )
    )
    response.headers["Location"] = f"/students/{created.id}"
    return created


@router.patch(
    "/students/{student_id}",
    tags=["students"],
    responses=ERRORS,
    dependencies=WRITE,
)
async def update_student(
    student_id: StudentId, data: StudentUpdate, service: ServiceDep
) -> StudentOut:
    """Змінює лише передані поля: бал, групу (переведення), ім'я, email."""
    changes = data.model_dump(exclude_unset=True)
    return await in_thread(
        lambda: StudentOut.from_student(
            service.update_student(student_id, changes)
        )
    )


@router.delete(
    "/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["students"],
    responses=ERRORS,
    dependencies=WRITE,
)
async def delete_student(
    student_id: StudentId, service: ServiceDep
) -> Response:
    """Видаляє студента."""
    await in_thread(lambda: service.delete_student(student_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/groups", tags=["groups"])
async def list_groups(service: ServiceDep) -> list[GroupStatisticsOut]:
    """Усі групи зі статистикою."""
    return await in_thread(
        lambda: [
            GroupStatisticsOut.from_stats(item)
            for item in service.group_report()
        ]
    )


@router.post(
    "/groups",
    status_code=status.HTTP_201_CREATED,
    tags=["groups"],
    responses=ERRORS,
    dependencies=WRITE,
)
async def create_group(
    data: GroupCreate, service: ServiceDep
) -> GroupStatisticsOut:
    """Створює групу."""

    def run() -> GroupStatisticsOut:
        group = service.create_group(data.name)
        return GroupStatisticsOut.from_stats(
            service.group_statistics(group.id)
        )

    return await in_thread(run)


@router.get("/groups/{group_id}/students", tags=["groups"], responses=ERRORS)
async def group_students(
    group_id: GroupId, service: ServiceDep
) -> list[StudentOut]:
    """Студенти групи."""

    def run() -> list[StudentOut]:
        found = service.students_of_group(group_id)
        return [StudentOut.from_student(item) for item in found]

    return await in_thread(run)


@router.get("/groups/{group_id}/statistics", tags=["groups"], responses=ERRORS)
async def group_statistics(
    group_id: GroupId, service: ServiceDep
) -> GroupStatisticsOut:
    """Кількість студентів, середній, найкращий і найгірший бал групи."""
    return await in_thread(
        lambda: GroupStatisticsOut.from_stats(
            service.group_statistics(group_id)
        )
    )


@router.post(
    "/groups/{group_id}/transfer",
    tags=["groups"],
    responses=ERRORS,
    dependencies=WRITE,
)
async def transfer_to_group(
    group_id: GroupId, data: TransferIn, service: ServiceDep
) -> TransferOut:
    """Переводить студентів до групи однією транзакцією (все або нічого)."""

    def run() -> TransferOut:
        service.get_group(group_id)
        moved = service.transfer_to_group(data.student_ids, group_id)
        return TransferOut(group_id=group_id, moved=moved)

    return await in_thread(run)


def load_statistics(
    factory: sessionmaker[Session], group_id: int
) -> GroupStatisticsOut:
    """Статистика групи в окремій сесії (для виклику з пулу потоків)."""
    with factory() as session:
        stats = StudentService(session).group_statistics(group_id)
        return GroupStatisticsOut.from_stats(stats)


@router.post("/statistics/groups", tags=["statistics"], responses=ERRORS)
async def batch_statistics(
    body: BatchStatisticsIn, request: Request
) -> list[GroupStatisticsOut]:
    """Статистика кількох груп паралельно: Task, gather, Semaphore, timeout."""
    runtime = await in_thread(lambda: get_runtime(request.app))

    async def one(group_id: int) -> GroupStatisticsOut:
        async with runtime.batch_semaphore:
            return await in_thread(
                lambda: load_statistics(runtime.session_factory, group_id)
            )

    tasks = [asyncio.create_task(one(group_id)) for group_id in body.group_ids]
    try:
        return list(
            await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=runtime.batch_timeout
            )
        )
    except TimeoutError as error:
        raise BatchTimeoutError(
            f"статистика не отримана за {runtime.batch_timeout} с"
        ) from error
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def error_status(error: Exception) -> int:
    """HTTP-код для винятку: 4xx/5xx за таблицею, інакше 400 або 500."""
    for error_type, code in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return code
    if isinstance(error, StudentManagerError):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


async def domain_error_handler(
    _request: Request, error: Exception
) -> JSONResponse:
    """Перетворює виняток сервісу на JSON {"error": ..., "detail": ...}."""
    name = re.sub(
        r"(?<!^)(?=[A-Z])", "_", type(error).__name__.removesuffix("Error")
    ).lower()
    body = ErrorOut(error=name, detail=str(error))
    return JSONResponse(
        status_code=error_status(error), content=body.model_dump()
    )


def create_app(
    database: str | None = None,
    *,
    batch_concurrency: int | None = None,
    batch_timeout: float | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Створює застосунок із налаштувань; решта параметрів їх перекриває."""
    overrides: dict[str, Any] = {}
    if database is not None:
        overrides["database_url"] = database
    if batch_concurrency is not None:
        overrides["batch_concurrency"] = batch_concurrency
    if batch_timeout is not None:
        overrides["batch_timeout"] = batch_timeout
    current = (settings or get_settings()).model_copy(update=overrides)

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        await in_thread(lambda: get_runtime(instance))
        logger.info(
            "%s %s запущено (%s)",
            current.app_name,
            __version__,
            current.environment,
        )
        try:
            yield
        finally:
            await in_thread(lambda: close_runtime(instance))

    application = FastAPI(
        title=current.app_name,
        version=__version__,
        description=(
            "Облік студентів і груп: REST API поверх шару збереження "
            "(production-збірка, ЛР10)."
        ),
        openapi_tags=TAGS,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    application.state.settings = current
    application.mount("/static", StaticFiles(directory=STATIC), name="static")
    application.include_router(router)
    application.add_exception_handler(
        StudentManagerError, domain_error_handler
    )

    @application.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        """Swagger UI зі статичних файлів пакета (без CDN)."""
        return get_swagger_ui_html(
            openapi_url=application.openapi_url or "/openapi.json",
            title="Student Manager API - Swagger UI",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
            swagger_favicon_url="",
        )

    return application


app = create_app()
