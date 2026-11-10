"""GET /health: стан сервісу, середовище, база даних, відсутність захисту."""

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from student_manager import __version__
from student_manager.api import create_app
from student_manager.config import Settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bare_client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(f"sqlite:///{tmp_path / 'empty.db'}")
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_ok_and_environment(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
        "version": __version__,
        "database": "ok",
    }


async def test_health_shows_the_configured_environment(
    api_db_url: str,
) -> None:
    settings = Settings(_env_file=None, environment="production")
    app: FastAPI = create_app(api_db_url, settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as http:
            body = (await http.get("/health")).json()
    assert body["environment"] == "production"


async def test_health_is_unavailable_without_a_migrated_database(
    bare_client: httpx.AsyncClient,
) -> None:
    async with bare_client:
        response = await bare_client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert (body["status"], body["database"]) == (
        "unavailable",
        "unavailable",
    )
    assert "sqlite" not in response.text


async def test_health_does_not_require_the_api_token(api_db_url: str) -> None:
    settings = Settings(_env_file=None, api_token="unit-test-token")
    app = create_app(api_db_url, settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as http:
            assert (await http.get("/health")).status_code == 200


async def test_health_is_listed_in_openapi(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert "get" in schema["paths"]["/health"]
    assert "HealthOut" in schema["components"]["schemas"]
