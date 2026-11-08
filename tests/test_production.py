"""Production-частина: конфігурація з environment, secrets, /health, X-API-Key, CLI, прогноз."""

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import create_engine

from bank_account_service import __version__
from bank_account_service.api import create_app
from bank_account_service.config import Settings
from bank_account_service.interest import accrue_python, forecast
from bank_account_service.main import main

pytestmark = pytest.mark.asyncio


async def test_defaults_without_environment() -> None:
    settings = Settings()
    assert (settings.app_env, settings.database_url, settings.log_level) == (
        "development",
        "sqlite:///bank.db",
        "INFO",
    )
    assert settings.api_token is None


async def test_empty_api_token_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "")
    assert Settings().api_token is None


async def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    url = "postgresql://bank:s3cret@db:5432/bank"  # pragma: allowlist secret
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("API_TOKEN", "token-from-env")
    settings = Settings()
    assert (settings.app_env, settings.log_level) == ("production", "DEBUG")
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "token-from-env"
    assert "token-from-env" not in repr(settings)
    assert settings.safe_database_url == "postgresql://bank:***@db:5432/bank"


async def test_dotenv_file_is_read_and_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("APP_ENV=production\nLOG_LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    settings = Settings()
    assert (settings.app_env, settings.log_level) == ("production", "ERROR")


@pytest.mark.parametrize(
    ("name", "value"), [("APP_ENV", "staging"), ("LOG_LEVEL", "LOUD"), ("CONFLICT_RETRIES", "-1")]
)
async def test_invalid_configuration_fails_fast(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


async def test_health_reports_version_environment_and_database(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "environment": "test",
        "database": "ok",
    }


async def test_health_is_503_when_database_is_unavailable(
    asgi_app: FastAPI, tmp_path: Path
) -> None:
    asgi_app.state.engine.dispose()
    asgi_app.state.engine = create_engine(f"sqlite:///{tmp_path / 'missing' / 'bank.db'}")
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/health")
    assert (response.status_code, response.json()["database"]) == (503, "error")


async def test_api_token_protects_changes_but_not_reads(settings: Settings) -> None:
    app = create_app(
        Settings(
            database_url=settings.database_url,
            app_env="test",
            api_token="s3cr3t-token",  # pragma: allowlist secret
            _env_file=None,
        )
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            body = {"full_name": "Олена Коваленко"}
            no_key = await http.post("/clients", json=body)
            wrong = await http.post("/clients", json=body, headers={"X-API-Key": "guess"})
            ok = await http.post("/clients", json=body, headers={"X-API-Key": "s3cr3t-token"})
            read = await http.get("/clients/1")
    assert (no_key.status_code, wrong.status_code, ok.status_code) == (401, 401, 201)
    assert no_key.headers["WWW-Authenticate"] == "ApiKey"
    assert read.status_code == 200


async def test_numpy_forecast_matches_python_baseline() -> None:
    balances = [0, 1825, 100_000, 1_525_075, 50_000_000]
    now, later = forecast(balances, 365)
    assert now == sum(balances)
    assert later == sum(accrue_python(balance, 365) for balance in balances)


async def test_interest_endpoint(client: httpx.AsyncClient, bank: dict[str, int]) -> None:
    response = await client.get("/statistics/interest", params={"currency": "UAH"})
    data = response.json()
    assert (data["accounts"], data["total_now"]) == (2, "1250.00")
    expected = Decimal(accrue_python(100_000, 365) + accrue_python(25_000, 365)).scaleb(-2)
    assert Decimal(data["total_after"]) == expected
    assert Decimal(data["interest"]) == expected - Decimal("1250.00")


async def test_cli_migrate_and_config_hide_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "data" / "bank.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("API_TOKEN", "super-secret-value")
    from bank_account_service.config import get_settings

    get_settings.cache_clear()
    try:
        assert main(["migrate"]) == 0
        assert main(["config"]) == 0
    finally:
        get_settings.cache_clear()
    assert database.exists()
    output = capsys.readouterr().out
    assert "super-secret-value" not in output
    assert "API_TOKEN         **********" in output
