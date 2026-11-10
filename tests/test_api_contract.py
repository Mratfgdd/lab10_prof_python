"""Контракт API: 422, OpenAPI, Swagger, lifespan."""

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from starlette.requests import Request

from student_manager.api import (
    create_app,
    domain_error_handler,
    error_status,
)
from student_manager.dependencies import close_runtime, get_runtime
from student_manager.exceptions import StudentManagerError
from student_manager.services import StudentService

pytestmark = pytest.mark.asyncio

VALID = {
    "first_name": "Софія",
    "last_name": "Гнатюк",
    "group_id": 1,
    "average_grade": 88.0,
}


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"first_name": "С"}, "first_name"),
        ({"last_name": ""}, "last_name"),
        ({"group_id": 0}, "group_id"),
        ({"group_id": "one"}, "group_id"),
        ({"average_grade": 150}, "average_grade"),
        ({"average_grade": -1}, "average_grade"),
        ({"average_grade": "a lot"}, "average_grade"),
        ({"email": "broken"}, "email"),
    ],
)
async def test_invalid_post_body_is_422_with_the_field_location(
    client: httpx.AsyncClient, override: dict[str, Any], field: str
) -> None:
    response = await client.post("/students", json={**VALID, **override})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]


async def test_missing_fields_and_unknown_fields_are_422(
    client: httpx.AsyncClient,
) -> None:
    missing = await client.post("/students", json={"first_name": "Софія"})
    assert missing.status_code == 422
    assert {tuple(e["loc"]) for e in missing.json()["detail"]} == {
        ("body", "last_name"),
        ("body", "group_id"),
        ("body", "average_grade"),
    }
    extra = await client.post("/students", json={**VALID, "role": "admin"})
    assert extra.status_code == 422


async def test_malformed_json_and_wrong_content_are_422(
    client: httpx.AsyncClient,
) -> None:
    broken = await client.post(
        "/students",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert broken.status_code == 422
    assert (await client.post("/students", json=[1, 2, 3])).status_code == 422


@pytest.mark.parametrize(
    "body", [{}, {"average_grade": None}, {"group_id": None}, {"x": 1}]
)
async def test_invalid_patch_bodies_are_422(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    assert (await client.patch("/students/1", json=body)).status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/students/0",
        "/students/-1",
        "/students/abc",
        "/groups/0/statistics",
        "/groups/x/students",
    ],
)
async def test_path_parameters_are_validated(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"min_grade": 101},
        {"max_grade": -1},
        {"group_id": 0},
        {"sort": "email"},
        {"order": "up"},
        {"last_name": ""},
    ],
)
async def test_query_parameters_are_validated(
    client: httpx.AsyncClient, params: dict[str, Any]
) -> None:
    assert (await client.get("/students", params=params)).status_code == 422


async def test_unknown_route_is_404_and_wrong_method_is_405(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/teachers")).status_code == 404
    response = await client.put("/students/1", json=VALID)
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]


async def test_openapi_describes_every_endpoint_of_the_task(
    client: httpx.AsyncClient,
) -> None:
    schema = (await client.get("/openapi.json")).json()
    operations = {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
    }
    assert {
        ("GET", "/students"),
        ("GET", "/students/{student_id}"),
        ("POST", "/students"),
        ("PATCH", "/students/{student_id}"),
        ("DELETE", "/students/{student_id}"),
        ("GET", "/groups/{group_id}/students"),
        ("GET", "/groups/{group_id}/statistics"),
        ("GET", "/health"),
    } <= operations
    assert schema["info"]["title"] == "Student Manager API"
    assert "StudentCreate" in schema["components"]["schemas"]


async def test_swagger_ui_is_served_from_the_package_without_cdn(
    client: httpx.AsyncClient,
) -> None:
    page = await client.get("/docs")
    assert page.status_code == 200
    assert "/static/swagger-ui-bundle.js" in page.text
    assert "cdn" not in page.text.lower()
    script = await client.get("/static/swagger-ui-bundle.js")
    assert (script.status_code, len(script.content) > 100_000) == (200, True)


async def test_missing_schema_is_reported_at_startup(tmp_path: Any) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'empty.db'}")
    with pytest.raises(Exception, match="alembic upgrade head"):
        async with app.router.lifespan_context(app):
            pass


async def test_application_factory_uses_the_given_database(
    api_db_path: Any, asgi_app: FastAPI, client: httpx.AsyncClient
) -> None:
    created = await client.post("/groups", json={"name": "PI-21"})
    assert created.status_code == 201
    engine = create_engine(f"sqlite:///{api_db_path}")
    with engine.connect() as connection:
        rows = connection.exec_driver_sql("SELECT name FROM groups").fetchall()
    engine.dispose()
    assert rows == [("PI-21",)]


async def test_unclassified_domain_error_is_a_structured_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_self: StudentService) -> None:
        raise StudentManagerError("щось пішло не так")

    monkeypatch.setattr(StudentService, "get_best_student", broken)
    response = await client.get("/students/best")
    assert response.status_code == 400
    assert response.json() == {
        "error": "student_manager",
        "detail": "щось пішло не так",
    }


async def test_application_works_without_lifespan_events(
    api_db_url: str,
) -> None:
    app = create_app(api_db_url)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        assert (
            await http.post("/groups", json={"name": "PI-21"})
        ).status_code == 201
        assert (await http.get("/students")).json() == []
        assert (
            await http.post("/statistics/groups", json={"group_ids": [1]})
        ).status_code == 200
    close_runtime(app)
    assert app.state.runtime is None


async def test_missing_schema_without_lifespan_is_a_structured_503(
    tmp_path: Any,
) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'empty.db'}")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        response = await http.get("/students")
    assert response.status_code == 503
    assert response.json()["error"] == "schema_missing"
    assert "alembic upgrade head" in response.json()["detail"]


async def test_runtime_is_created_once_and_shared(api_db_url: str) -> None:
    app = create_app(api_db_url)
    first = get_runtime(app)
    assert get_runtime(app) is first
    close_runtime(app)
    second = get_runtime(app)
    assert second is not first
    close_runtime(app)
    close_runtime(app)


async def test_error_status_falls_back_to_400_and_500() -> None:
    assert error_status(StudentManagerError("щось пішло не так")) == 400
    assert error_status(RuntimeError("збій")) == 500


async def test_error_handler_answers_500_for_a_foreign_exception() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/"})
    response = await domain_error_handler(request, RuntimeError("збій"))
    assert response.status_code == 500
    assert json.loads(bytes(response.body)) == {
        "error": "runtime",
        "detail": "збій",
    }
