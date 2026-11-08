"""REST API банківської системи (FastAPI) над Service/Repository Layer з ЛР7.

Запуск: bank-account-service serve (міграції + uvicorn) або uvicorn bank_account_service.api:app.
Конфігурація - environment variables (config.Settings).
"""

import asyncio
import logging
import random
import re
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from bank_account_service import __version__
from bank_account_service.config import Settings, get_settings
from bank_account_service.database import (
    database_ready,
    ensure_schema,
    make_engine,
    make_session_factory,
)
from bank_account_service.exceptions import (
    AccountNotEmptyError,
    AccountNotFoundError,
    BankError,
    ClientNotFoundError,
    ConcurrentUpdateError,
    DuplicateAccountError,
    InsufficientFundsError,
    SchemaMissingError,
)
from bank_account_service.interest import forecast
from bank_account_service.schemas import (
    AccountCreate,
    AccountOut,
    AccountType,
    AccountUpdate,
    AmountIn,
    ClientCreate,
    ClientFundsOut,
    ClientOut,
    CurrencyTotal,
    ErrorOut,
    FundsOut,
    HealthOut,
    InterestOut,
    Operation,
    TransactionOut,
    TransferCreate,
    TransferOut,
)
from bank_account_service.services import BankService
from bank_account_service.value_objects import Money

T = TypeVar("T")
STATIC = Path(__file__).with_name("static")
logger = logging.getLogger(__name__)
TAGS = [
    {"name": "service", "description": "Стан сервісу"},
    {"name": "clients", "description": "Клієнти банку"},
    {"name": "accounts", "description": "Рахунки: CRUD, баланс, пошук, фільтри"},
    {"name": "operations", "description": "Поповнення, списання, переказ, історія"},
    {"name": "statistics", "description": "Загальна сума коштів, прогноз відсотків"},
]
ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorOut} for code in (404, 409, 422)}
STATUS_BY_ERROR: list[tuple[type[BankError], int]] = [
    (AccountNotFoundError, status.HTTP_404_NOT_FOUND),
    (ClientNotFoundError, status.HTTP_404_NOT_FOUND),
    (InsufficientFundsError, status.HTTP_409_CONFLICT),
    (DuplicateAccountError, status.HTTP_409_CONFLICT),
    (AccountNotEmptyError, status.HTTP_409_CONFLICT),
    (ConcurrentUpdateError, status.HTTP_409_CONFLICT),
    (SchemaMissingError, status.HTTP_503_SERVICE_UNAVAILABLE),
]


async def get_service(request: Request) -> AsyncIterator[BankService]:
    """Dependency injection: окрема сесія БД на кожен запит, закривається після відповіді.

    Асинхронна залежність із finally: сесія закривається і тоді, коли обробку запиту
    скасовано (клієнт розірвав з'єднання, timeout). Синхронну yield-залежність FastAPI при
    CancelledError не завершує - сесія лишалася б відкритою з'єднанням із пулу.
    """
    session = request.app.state.session_factory()
    try:
        yield BankService(session)
    finally:
        session.close()


ServiceDep = Annotated[BankService, Depends(get_service)]
AccountId = Annotated[int, PathParam(gt=0, description="id рахунку")]


def conflict_retries(request: Request) -> int:
    retries: int = request.app.state.conflict_retries
    return retries


RetriesDep = Annotated[int, Depends(conflict_retries)]


async def in_thread(function: Callable[[], T], *, retries: int = 0) -> T:
    """Сервіс ЛР7 синхронний (SQLAlchemy + sqlite3): виконується в пулі потоків, щоб
    очікування диска не блокувало event loop і інші запити обслуговувалися паралельно.

    retries: при конфлікті версій (optimistic lock) транзакцію вже відкочено, тож операцію
    можна безпечно повторити з актуальними даними; пауза з jitter розводить «суперників».
    """
    for attempt in range(retries + 1):
        try:
            return await run_in_threadpool(function)
        except ConcurrentUpdateError:
            if attempt == retries:
                raise
            await asyncio.sleep(random.uniform(0, 0.02 * (attempt + 1)))  # noqa: S311
    raise AssertionError("unreachable")


api_key_header = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="Потрібен, якщо сервер запущено з API_TOKEN"
)


def require_api_key(
    request: Request, api_key: Annotated[str | None, Depends(api_key_header)]
) -> None:
    """Зміни даних дозволено лише з ключем, якщо API_TOKEN задано в середовищі.
    compare_digest порівнює за сталий час (захист від timing-атак)."""
    token = request.app.state.settings.api_token
    if token is not None and not secrets.compare_digest(
        (api_key or "").encode(), token.get_secret_value().encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


router = APIRouter()
write = APIRouter(
    dependencies=[Depends(require_api_key)],
    responses={401: {"description": "Немає або неправильний X-API-Key"}},
)


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": "Bank Account Service", "version": __version__, "docs": "/docs"}


@router.get(
    "/health",
    tags=["service"],
    responses={503: {"model": HealthOut, "description": "БД недоступна"}},
)
async def health(request: Request, response: Response) -> HealthOut:
    """Liveness/readiness: процес працює, БД доступна й мігрована (для Docker HEALTHCHECK)."""
    settings: Settings = request.app.state.settings
    ready = await run_in_threadpool(database_ready, request.app.state.engine)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(
        status="ok" if ready else "unavailable",
        version=__version__,
        environment=settings.app_env,
        database="ok" if ready else "error",
    )


@write.post("/clients", status_code=status.HTTP_201_CREATED, tags=["clients"], responses=ERRORS)
async def create_client(body: ClientCreate, service: ServiceDep) -> ClientOut:
    return await in_thread(
        lambda: ClientOut.model_validate(service.register_client(body.full_name))
    )


@router.get("/clients/{client_id}", tags=["clients"], responses=ERRORS)
async def get_client(client_id: Annotated[int, PathParam(gt=0)], service: ServiceDep) -> ClientOut:
    return await in_thread(lambda: ClientOut.model_validate(service.get_client(client_id)))


@write.post("/accounts", status_code=status.HTTP_201_CREATED, tags=["accounts"], responses=ERRORS)
async def create_account(body: AccountCreate, service: ServiceDep) -> AccountOut:
    opening = Money(body.opening_balance, body.currency)
    return await in_thread(
        lambda: AccountOut.model_validate(
            service.open_account(body.client_id, body.number, opening, body.account_type)
        )
    )


@router.get("/accounts", tags=["accounts"])
async def list_accounts(
    service: ServiceDep,
    number: Annotated[str | None, Query(pattern=r"^UA-\d{4,8}$")] = None,
    client_id: Annotated[int | None, Query(gt=0)] = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    account_type: AccountType | None = None,
    min_balance: Annotated[Decimal | None, Query(ge=0)] = None,
    sort: Literal["number", "balance"] = "number",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AccountOut]:
    """Пошук рахунку і фільтрація (query parameters), сортування, пагінація."""
    return await in_thread(
        lambda: [
            AccountOut.model_validate(a)
            for a in service.accounts.search(
                number=number,
                client_id=client_id,
                currency=currency,
                account_type=account_type,
                min_balance=min_balance,
                order_by=sort,
                descending=order == "desc",
                limit=limit,
                offset=offset,
            )
        ]
    )


@router.get("/accounts/{account_id}", tags=["accounts"], responses=ERRORS)
async def get_account(account_id: AccountId, service: ServiceDep) -> AccountOut:
    """Рахунок і його баланс."""
    return await in_thread(lambda: AccountOut.model_validate(service.get_account(account_id)))


@write.patch("/accounts/{account_id}", tags=["accounts"], responses=ERRORS)
async def update_account(
    account_id: AccountId, body: AccountUpdate, service: ServiceDep
) -> AccountOut:
    def run() -> AccountOut:
        account = service.get_account(account_id)
        if body.account_type is not None:
            account = service.change_account_type(account.number, body.account_type)
        return AccountOut.model_validate(account)

    return await in_thread(run)


@write.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["accounts"],
    responses=ERRORS,
)
async def close_account(account_id: AccountId, service: ServiceDep) -> Response:
    """Закрити можна лише рахунок із нульовим балансом (інакше 409)."""
    await in_thread(lambda: service.close_account(service.get_account(account_id).number))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/accounts/{account_id}/transactions", tags=["operations"], responses=ERRORS)
async def account_history(
    account_id: AccountId,
    service: ServiceDep,
    operation: Operation | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TransactionOut]:
    def run() -> list[TransactionOut]:
        account = service.get_account(account_id)
        history = service.transactions.history(account.id, operation=operation, limit=limit)
        return [TransactionOut.model_validate(t) for t in history]

    return await in_thread(run)


@write.post(
    "/accounts/{account_id}/deposit",
    status_code=status.HTTP_201_CREATED,
    tags=["operations"],
    responses=ERRORS,
)
async def deposit(
    account_id: AccountId, body: AmountIn, service: ServiceDep, retries: RetriesDep
) -> TransactionOut:
    def run() -> TransactionOut:
        account = service.get_account(account_id)
        return TransactionOut.model_validate(
            service.deposit(account.number, Money(body.amount, account.currency))
        )

    return await in_thread(run, retries=retries)


@write.post(
    "/accounts/{account_id}/withdraw",
    status_code=status.HTTP_201_CREATED,
    tags=["operations"],
    responses=ERRORS,
)
async def withdraw(
    account_id: AccountId, body: AmountIn, service: ServiceDep, retries: RetriesDep
) -> TransactionOut:
    """Від'ємний баланс заборонено: 409 insufficient_funds."""

    def run() -> TransactionOut:
        account = service.get_account(account_id)
        return TransactionOut.model_validate(
            service.withdraw(account.number, Money(body.amount, account.currency))
        )

    return await in_thread(run, retries=retries)


@write.post(
    "/transfers", status_code=status.HTTP_201_CREATED, tags=["operations"], responses=ERRORS
)
async def transfer(body: TransferCreate, service: ServiceDep, retries: RetriesDep) -> TransferOut:
    """Атомарний переказ (транзакція ЛР7): списання, зарахування і два записи - або нічого."""

    def run() -> TransferOut:
        source = service.get_account(body.source_id)
        target = service.get_account(body.target_id)
        debit, credit = service.transfer_money(
            source.number, target.number, Money(body.amount, source.currency)
        )
        return TransferOut(
            debit=TransactionOut.model_validate(debit), credit=TransactionOut.model_validate(credit)
        )

    return await in_thread(run, retries=retries)


@router.get("/statistics/funds", tags=["statistics"])
async def funds(service: ServiceDep) -> FundsOut:
    """Загальна сума коштів у кожній валюті та за клієнтами (SUM, JOIN + GROUP BY)."""

    def run() -> FundsOut:
        totals = [
            CurrencyTotal(currency=c, total=service.total_funds(c).amount)
            for c in service.accounts.currencies()
        ]
        by_client = [ClientFundsOut.model_validate(row) for row in service.funds_by_client()]
        return FundsOut(totals=totals, by_client=by_client)

    return await in_thread(run)


@router.get("/statistics/interest", tags=["statistics"])
async def interest_forecast(
    service: ServiceDep,
    currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$")] = "UAH",
    days: Annotated[int, Query(ge=1, le=3650)] = 365,
) -> InterestOut:
    """Прогноз: 10 % річних із щоденною капіталізацією для всіх рахунків валюти (NumPy, ЛР9)."""

    def run() -> InterestOut:
        balances = service.accounts.balances_in_cents(currency)
        now, later = forecast(balances, days)
        return InterestOut(
            currency=currency,
            days=days,
            accounts=len(balances),
            total_now=Decimal(now).scaleb(-2),
            total_after=Decimal(later).scaleb(-2),
            interest=Decimal(later - now).scaleb(-2),
        )

    return await in_thread(run)


def error_status(error: BankError) -> int:
    for error_type, code in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return code
    return status.HTTP_422_UNPROCESSABLE_CONTENT if isinstance(error, ValueError) else 400


async def bank_error_handler(_request: Request, error: Exception) -> JSONResponse:
    """Custom exception handler: виняток сервісу -> HTTP status code + структурований JSON."""
    if not isinstance(error, BankError):
        raise TypeError(error)
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__.removesuffix("Error")).lower()
    body = ErrorOut(error=name, detail=str(error))
    return JSONResponse(status_code=error_status(error), content=body.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Фабрика застосунку; тести передають Settings з окремою тестовою БД."""
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(config.database_url)
        try:
            await run_in_threadpool(ensure_schema, engine)
            app.state.engine = engine
            app.state.session_factory = make_session_factory(engine)
            logger.info(
                "%s %s started: env=%s, db=%s, api token %s",
                config.app_name,
                __version__,
                config.app_env,
                config.safe_database_url,
                "set" if config.api_token else "not set",
            )
            yield
        finally:
            engine.dispose()
        logger.info("%s stopped", config.app_name)

    app = FastAPI(
        title=config.app_name,
        version=__version__,
        summary="ЛР10, варіант 4: клієнти, рахунки, операції та перекази",
        openapi_tags=TAGS,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = config
    app.state.conflict_retries = config.conflict_retries
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(router)
    app.include_router(write)
    app.add_exception_handler(BankError, bank_error_handler)

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{config.app_name} - Swagger UI",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
            swagger_favicon_url="",
        )

    return app


def __getattr__(name: str) -> FastAPI:
    """uvicorn bank_account_service.api:app - застосунок створюється при першому зверненні,
    а не під час імпорту модуля (тести й CLI не читають конфігурацію зайвий раз)."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
