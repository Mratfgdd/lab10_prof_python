"""Service Layer: бізнес-логіка банку поверх репозиторіїв.

Кожен публічний метод, що змінює дані, - одна транзакція БД: commit, якщо все вдалося,
rollback - якщо виник будь-який виняток.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from bank_account_service.exceptions import (
    AccountNotEmptyError,
    AccountNotFoundError,
    ClientNotFoundError,
    ConcurrentUpdateError,
    CurrencyError,
    DuplicateAccountError,
    InsufficientFundsError,
    InvalidAmountError,
)
from bank_account_service.models import Account, Client, Transaction
from bank_account_service.repositories import (
    AccountRepository,
    ClientFunds,
    ClientRepository,
    TransactionRepository,
)
from bank_account_service.value_objects import AccountNumber, Money

ACCOUNT_TYPES = ("current", "savings")
DEBITS = ("withdraw", "transfer_out")


class BankService:
    def __init__(self, session: Session, *, clock: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self.clients = ClientRepository(session)
        self.accounts = AccountRepository(session)
        self.transactions = TransactionRepository(session)
        self._clock = clock if clock is not None else datetime.now

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Межі транзакції: commit після успішного блоку, rollback при будь-якій помилці."""
        try:
            yield
            self.session.commit()
        except StaleDataError as error:
            self.session.rollback()
            raise ConcurrentUpdateError("рахунок змінила інша операція, повторіть") from error
        except Exception:
            self.session.rollback()
            raise

    def register_client(self, full_name: str) -> Client:
        if not full_name.strip():
            raise ValueError("ім'я клієнта не може бути порожнім")
        with self._transaction():
            return self.clients.add(Client(full_name=full_name.strip()))

    def open_account(
        self, client_id: int, number: str, opening: Money, account_type: str = "current"
    ) -> Account:
        AccountNumber(number)
        if account_type not in ACCOUNT_TYPES:
            raise ValueError(f"невідомий тип рахунку: {account_type!r}")
        with self._transaction():
            account = Account(
                number=number,
                client=self.get_client(client_id),
                currency=opening.currency,
                balance=opening.amount,
                account_type=account_type,
            )
            try:
                self.accounts.add(account)
            except IntegrityError as error:
                if "UNIQUE constraint failed: accounts.number" not in str(error.orig):
                    raise
                raise DuplicateAccountError(f"рахунок {number} уже існує") from error
            if opening:
                self._record(account, "deposit", opening)
        return account

    def find_account(self, number: str) -> Account:
        account = self.accounts.get_by_number(AccountNumber(number).value)
        if account is None:
            raise AccountNotFoundError(f"рахунок {number} не знайдено")
        return account

    def get_account(self, account_id: int) -> Account:
        """ЛР8: REST API адресує рахунки за id (ресурс /accounts/{id})."""
        account = self.accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"рахунок з id={account_id} не знайдено")
        return account

    def balance(self, number: str) -> Money:
        account = self.find_account(number)
        return Money(account.balance, account.currency)

    def history(self, number: str) -> list[Transaction]:
        return self.transactions.history(self.find_account(number).id)

    def total_funds(self, currency: str = "UAH") -> Money:
        return Money(self.accounts.total_funds(currency), currency)

    def funds_by_client(self) -> list[ClientFunds]:
        return self.accounts.funds_by_client()

    def deposit(self, number: str, amount: Money) -> Transaction:
        with self._transaction():
            return self._post(self.find_account(number), "deposit", amount)

    def withdraw(self, number: str, amount: Money) -> Transaction:
        with self._transaction():
            return self._post(self.find_account(number), "withdraw", amount)

    def transfer_money(
        self, source: str, target: str, amount: Money
    ) -> tuple[Transaction, Transaction]:
        """Атомарний переказ: списання, зарахування і два записи transactions - або нічого."""
        if source == target:
            raise ValueError("переказ на той самий рахунок")
        with self._transaction():
            debit = self._post(self.find_account(source), "transfer_out", amount)
            credit = self._post(self.find_account(target), "transfer_in", amount)
        return debit, credit

    def rename_client(self, client_id: int, full_name: str) -> Client:
        with self._transaction():
            client = self.get_client(client_id)
            client.full_name = full_name.strip()
        return client

    def change_account_type(self, number: str, account_type: str) -> Account:
        if account_type not in ACCOUNT_TYPES:
            raise ValueError(f"невідомий тип рахунку: {account_type!r}")
        with self._transaction():
            account = self.find_account(number)
            account.account_type = account_type
        return account

    def close_account(self, number: str) -> None:
        with self._transaction():
            account = self.find_account(number)
            if account.balance:
                raise AccountNotEmptyError(f"на рахунку {number} лишилися кошти")
            self.accounts.delete(account)

    def delete_client(self, client_id: int) -> None:
        with self._transaction():
            self.clients.delete(self.get_client(client_id))

    def get_client(self, client_id: int) -> Client:
        client = self.clients.get(client_id)
        if client is None:
            raise ClientNotFoundError(f"клієнта з id={client_id} не знайдено")
        return client

    def _post(self, account: Account, operation: str, amount: Money) -> Transaction:
        """Змінює баланс і записує операцію; від'ємний баланс заборонений (як у ЛР1)."""
        if amount.currency != account.currency:
            raise CurrencyError(
                f"рахунок {account.number} у {account.currency}, сума в {amount.currency}"
            )
        if not amount:
            raise InvalidAmountError("сума операції має бути більшою за нуль")
        if operation in DEBITS:
            if amount.amount > account.balance:
                raise InsufficientFundsError(
                    f"{account.number}: недостатньо коштів (потрібно {amount}, "
                    f"є {Money(account.balance, account.currency)})"
                )
            account.balance -= amount.amount
        else:
            account.balance += amount.amount
        return self._record(account, operation, amount)

    def _record(self, account: Account, operation: str, amount: Money) -> Transaction:
        return self.transactions.add(
            Transaction(
                account=account,
                operation=operation,
                amount=amount.amount,
                balance_after=account.balance,
                created_at=self._clock(),
            )
        )
