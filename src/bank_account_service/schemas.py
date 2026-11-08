"""Pydantic-схеми REST API: валідація запитів (request body) і форма відповідей (JSON)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AccountType = Literal["current", "savings"]
Operation = Literal["deposit", "withdraw", "transfer_in", "transfer_out"]
EntityId = Annotated[int, Field(gt=0)]
Amount = Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=2, examples=["500.00"])]


class ClientCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=100, examples=["Олена Коваленко"])


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class AccountCreate(BaseModel):
    client_id: EntityId
    number: str = Field(pattern=r"^UA-\d{4,8}$", examples=["UA-1001"])
    currency: str = Field(default="UAH", pattern=r"^[A-Z]{3}$")
    opening_balance: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    account_type: AccountType = "current"


class AccountUpdate(BaseModel):
    """PATCH: передаються лише поля, які треба змінити."""

    account_type: AccountType | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    client_id: int
    currency: str
    balance: Decimal
    account_type: AccountType


class AmountIn(BaseModel):
    amount: Amount


class TransferCreate(BaseModel):
    source_id: EntityId
    target_id: EntityId
    amount: Amount

    @model_validator(mode="after")
    def different_accounts(self) -> Self:
        if self.source_id == self.target_id:
            raise ValueError("рахунки відправника й отримувача мають відрізнятися")
        return self


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    operation: Operation
    amount: Decimal
    balance_after: Decimal
    created_at: datetime


class TransferOut(BaseModel):
    debit: TransactionOut
    credit: TransactionOut


class CurrencyTotal(BaseModel):
    currency: str
    total: Decimal


class ClientFundsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client: str
    currency: str
    accounts: int
    total: Decimal


class FundsOut(BaseModel):
    totals: list[CurrencyTotal]
    by_client: list[ClientFundsOut]


class HealthOut(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
    environment: str
    database: Literal["ok", "error"]


class InterestOut(BaseModel):
    currency: str
    days: int
    accounts: int
    total_now: Decimal
    total_after: Decimal
    interest: Decimal


class ErrorOut(BaseModel):
    """Структурована помилка предметної області (404, 409, 422 від BankService)."""

    error: str = Field(examples=["insufficient_funds"])
    detail: str
