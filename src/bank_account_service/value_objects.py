"""Незмінні value objects з ЛР6: гроші та номер рахунку."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import total_ordering
from typing import Self

from bank_account_service.exceptions import (
    CurrencyError,
    InvalidAccountNumberError,
    InvalidAmountError,
)

CENT = Decimal("0.01")
ACCOUNT_PATTERN = re.compile(r"UA-\d{4,8}")


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "UAH"

    def __post_init__(self) -> None:
        if not self.amount.is_finite() or self.amount < 0:
            raise InvalidAmountError("сума має бути скінченною і невід'ємною")
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise CurrencyError(f"некоректний код валюти: {self.currency!r}")
        object.__setattr__(self, "amount", self.amount.quantize(CENT, ROUND_HALF_UP))

    @classmethod
    def of(cls, value: str | int | Decimal, currency: str = "UAH") -> Self:
        if isinstance(value, float):
            raise TypeError("float не використовується для грошей")
        try:
            return cls(Decimal(value), currency)
        except InvalidOperation as error:
            raise InvalidAmountError(f"не число: {value!r}") from error

    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyError(f"різні валюти: {self.currency} і {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount < other.amount

    def __bool__(self) -> bool:
        return self.amount != 0

    def __str__(self) -> str:
        return f"{self.amount:,.2f} {self.currency}".replace(",", " ")


@dataclass(frozen=True, slots=True, order=True)
class AccountNumber:
    value: str

    def __post_init__(self) -> None:
        if not ACCOUNT_PATTERN.fullmatch(self.value):
            raise InvalidAccountNumberError(f"некоректний номер рахунку: {self.value!r}")

    def __str__(self) -> str:
        return self.value
