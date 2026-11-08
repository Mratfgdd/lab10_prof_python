"""Repository Pattern: доступ до даних через SQLAlchemy ORM.

Репозиторії не викликають commit(): межі транзакції визначає сервіс, тому кілька змін
(списання, зарахування, записи історії) потрапляють в одну транзакцію.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from sqlalchemy import Select, func, inspect, select
from sqlalchemy.orm import Session

from bank_account_service.models import Account, Base, Client, Transaction

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """Generic Repository: CRUD, спільний для всіх ORM-моделей."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, entity_id: int) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def get_all(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        """Сторінка записів у порядку первинного ключа (пагінація LIMIT/OFFSET)."""
        statement = (
            select(self.model)
            .order_by(*inspect(self.model).primary_key)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement))

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(self.model)) or 0

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()


class ClientRepository(Repository[Client]):
    model = Client

    def find_by_name(self, fragment: str) -> list[Client]:
        statement = (
            select(Client).where(Client.full_name.contains(fragment)).order_by(Client.full_name)
        )
        return list(self.session.scalars(statement))


@dataclass(frozen=True, slots=True)
class ClientFunds:
    client: str
    currency: str
    accounts: int
    total: Decimal


class AccountRepository(Repository[Account]):
    model = Account

    def get_by_number(self, number: str) -> Account | None:
        return self.session.scalar(select(Account).where(Account.number == number))

    def search(
        self,
        *,
        number: str | None = None,
        client_id: int | None = None,
        currency: str | None = None,
        account_type: str | None = None,
        min_balance: Decimal | None = None,
        order_by: Literal["number", "balance"] = "number",
        descending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Account]:
        """Фільтри комбінуються через AND; сортування і пагінація виконуються в SQL."""
        statement: Select[tuple[Account]] = select(Account)
        if number is not None:
            statement = statement.where(Account.number == number)
        if client_id is not None:
            statement = statement.where(Account.client_id == client_id)
        if currency is not None:
            statement = statement.where(Account.currency == currency)
        if account_type is not None:
            statement = statement.where(Account.account_type == account_type)
        if min_balance is not None:
            statement = statement.where(Account.balance >= min_balance)
        column = Account.balance if order_by == "balance" else Account.number
        statement = statement.order_by(column.desc() if descending else column.asc(), Account.id)
        return list(self.session.scalars(statement.limit(limit).offset(offset)))

    def currencies(self) -> list[str]:
        statement = select(Account.currency).distinct().order_by(Account.currency)
        return list(self.session.scalars(statement))

    def balances_in_cents(self, currency: str) -> list[int]:
        statement = select(Account.balance).where(Account.currency == currency)
        return [int(balance * 100) for balance in self.session.scalars(statement)]

    def total_funds(self, currency: str) -> Decimal:
        """SUM(balance_cents) у SQL; порожня вибірка дає NULL -> 0."""
        total = self.session.scalar(
            select(func.sum(Account.balance)).where(Account.currency == currency)
        )
        return total if total is not None else Decimal("0.00")

    def funds_by_client(self) -> list[ClientFunds]:
        """JOIN clients-accounts + GROUP BY: кількість рахунків і сума коштів клієнта."""
        total = func.sum(Account.balance).label("total")
        statement = (
            select(Client.full_name, Account.currency, func.count(Account.id), total)
            .join(Account, Account.client_id == Client.id)
            .group_by(Client.id, Client.full_name, Account.currency)
            .order_by(Account.currency, total.desc())
        )
        return [ClientFunds(*row) for row in self.session.execute(statement)]


class TransactionRepository(Repository[Transaction]):
    model = Transaction

    def history(
        self, account_id: int, *, operation: str | None = None, limit: int | None = None
    ) -> list[Transaction]:
        statement = select(Transaction).where(Transaction.account_id == account_id)
        if operation is not None:
            statement = statement.where(Transaction.operation == operation)
        statement = statement.order_by(Transaction.created_at, Transaction.id).limit(limit)
        return list(self.session.scalars(statement))
