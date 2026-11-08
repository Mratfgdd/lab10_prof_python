"""Ієрархія винятків застосунку (з ЛР5–ЛР6, доповнена помилками сховища)."""


class BankError(Exception):
    """Базова помилка предметної області."""


class InvalidAmountError(BankError, ValueError):
    """Сума від'ємна, нульова для операції або не є числом."""


class InvalidAccountNumberError(BankError, ValueError):
    """Номер рахунку не відповідає формату."""


class CurrencyError(BankError, ValueError):
    """Валюти операндів різні або код валюти некоректний."""


class InsufficientFundsError(BankError):
    """Списання зробило б баланс від'ємним."""


class AccountNotFoundError(BankError, LookupError):
    """Рахунок не знайдено."""


class ClientNotFoundError(BankError, LookupError):
    """Клієнта не знайдено."""


class DuplicateAccountError(BankError):
    """Рахунок із таким номером уже існує (UNIQUE accounts.number)."""


class AccountNotEmptyError(BankError):
    """Закрити можна лише рахунок із нульовим балансом."""


class ConcurrentUpdateError(BankError):
    """Рахунок змінила інша транзакція між читанням і записом (optimistic lock)."""


class SchemaMissingError(BankError):
    """База даних не ініціалізована міграціями."""
