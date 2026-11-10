"""Захист записів заголовком X-API-Key, коли задано API_TOKEN."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from student_manager.api import create_app
from student_manager.config import Settings

pytestmark = pytest.mark.asyncio

TOKEN = "unit-test-token"
NEW_STUDENT = {
    "first_name": "Софія",
    "last_name": "Гнатюк",
    "group_id": 1,
    "average_grade": 88.0,
}


@pytest_asyncio.fixture
async def secured(api_db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(_env_file=None, api_token=TOKEN)
    app = create_app(api_db_url, settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as http:
            yield http


async def test_write_without_key_is_unauthorized(
    secured: httpx.AsyncClient,
) -> None:
    response = await secured.post("/groups", json={"name": "PI-31"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert TOKEN not in response.text


async def test_write_with_wrong_key_is_unauthorized(
    secured: httpx.AsyncClient,
) -> None:
    response = await secured.post(
        "/groups", json={"name": "PI-31"}, headers={"X-API-Key": "wrong-token"}
    )
    assert response.status_code == 401


async def test_write_with_correct_key_succeeds(
    secured: httpx.AsyncClient,
) -> None:
    headers = {"X-API-Key": TOKEN}
    created = await secured.post(
        "/groups", json={"name": "PI-31"}, headers=headers
    )
    assert created.status_code == 201
    group_id = created.json()["group_id"]
    student = {**NEW_STUDENT, "group_id": group_id}
    added = await secured.post("/students", json=student, headers=headers)
    assert added.status_code == 201


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/students", NEW_STUDENT),
        ("PATCH", "/students/1", {"average_grade": 70}),
        ("DELETE", "/students/1", None),
        ("POST", "/groups", {"name": "PI-32"}),
        ("POST", "/groups/1/transfer", {"student_ids": [1]}),
    ],
)
async def test_every_write_endpoint_is_protected(
    secured: httpx.AsyncClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    response = await secured.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/", "/health", "/students", "/groups", "/openapi.json", "/docs"],
)
async def test_reading_stays_open(
    secured: httpx.AsyncClient, path: str
) -> None:
    assert (await secured.get(path)).status_code == 200


async def test_without_a_token_writes_are_open(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/groups", json={"name": "PI-33"})
    assert response.status_code == 201


async def test_header_with_non_ascii_text_is_rejected_not_crashing(
    secured: httpx.AsyncClient,
) -> None:
    response = await secured.post(
        "/groups",
        json={"name": "PI-34"},
        headers={b"X-API-Key": "ключ".encode()},
    )
    assert response.status_code == 401
