"""CLI асинхронного клієнта (через справжній uvicorn) і value objects гроші/номер рахунку."""

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from bank_account_service.api import create_app
from bank_account_service.config import Settings
from bank_account_service.exceptions import (
    CurrencyError,
    InvalidAccountNumberError,
    InvalidAmountError,
)
from bank_account_service.external_api import main as client_main
from bank_account_service.value_objects import AccountNumber, Money


def test_client_cli_overview_over_http(
    serve: Callable[[FastAPI], str], settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    base_url = serve(create_app(settings))
    with httpx.Client(base_url=base_url) as http:
        http.post("/clients", json={"full_name": "Олена Коваленко"})
        http.post(
            "/accounts", json={"client_id": 1, "number": "UA-1001", "opening_balance": "15250.75"}
        )
    code = client_main(["overview", "1", "99", "--base-url", base_url, "--retries", "1"])
    output = capsys.readouterr().out
    assert code == 2
    assert "UA-1001" in output
    assert "15 250.75 UAH" in output
    assert "HTTP 404" in output


def test_money_arithmetic_and_validation() -> None:
    assert Money.of("10.005") == Money(Decimal("10.01"))
    assert Money.of(5) + Money.of("2.50") == Money.of("7.50")
    assert Money.of(5) - Money.of("2.50") == Money.of("2.50")
    assert Money.of(1) < Money.of(2)
    assert not Money.of(0)
    assert str(Money.of("15250.75")) == "15 250.75 UAH"
    with pytest.raises(CurrencyError):
        Money.of(1) + Money.of(1, "USD")
    with pytest.raises(InvalidAmountError):
        Money.of("abc")
    with pytest.raises(InvalidAmountError):
        Money.of(-1)
    with pytest.raises(TypeError):
        Money.of(0.1)  # type: ignore[arg-type]
    with pytest.raises(CurrencyError):
        Money.of(1, "uah")


def test_account_number_format() -> None:
    assert str(AccountNumber("UA-1001")) == "UA-1001"
    with pytest.raises(InvalidAccountNumberError):
        AccountNumber("1001")
