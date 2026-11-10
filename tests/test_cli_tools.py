"""student-api-client і tools/call_api.py."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from support import Serve

import call_api
from student_manager.api import create_app
from student_manager.external_api import main


@pytest.fixture
def server(serve: Serve, api_db_url: str) -> str:
    base_url = serve(create_app(api_db_url))
    with httpx.Client(base_url=base_url) as http:
        http.post("/groups", json={"name": "PI-21"})
        http.post("/groups", json={"name": "PI-22"})
        http.post(
            "/students",
            json={
                "first_name": "Олена",
                "last_name": "Коваленко",
                "group_id": 1,
                "average_grade": 90.5,
            },
        )
    return base_url


def test_client_prints_a_table_with_statistics_of_several_groups(
    server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["stats", "1", "2", "--base-url", server, "--concurrency", "2"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "2 групи, одночасно не більше 2 запитів" in out
    assert "PI-21" in out
    assert "90.50" in out
    assert "HTTP-запитів: 2" in out


def test_client_reports_unknown_groups_and_exits_with_code_2(
    server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["stats", "1", "999", "--base-url", server])
    out = capsys.readouterr().out
    assert code == 2
    assert "999  помилка: HTTP 404: групу з id=999 не знайдено" in out


def test_client_reports_an_unreachable_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        ["stats", "1", "--base-url", "http://127.0.0.1:9", "--retries", "1"]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "ApiUnavailableError" in out


def test_client_fails_when_the_deadline_is_exceeded(
    serve: Serve, capsys: pytest.CaptureFixture[str]
) -> None:
    slow = FastAPI()

    @slow.get("/groups/{group_id}/statistics")
    async def slow_statistics(group_id: int) -> dict[str, int]:
        await asyncio.sleep(1)
        return {"group_id": group_id}

    code = main(["stats", "1", "--base-url", serve(slow), "--deadline", "0.1"])
    assert code == 1
    assert "не отримана за 0.1 с" in capsys.readouterr().err


def test_parse_body_builds_json_from_arguments() -> None:
    assert call_api.parse_body(
        ["name=PI-21", "group_id:=3", "tags:=[1, 2]"]
    ) == {
        "name": "PI-21",
        "group_id": 3,
        "tags": [1, 2],
    }
    assert call_api.parse_body([]) is None


def test_render_prints_short_json_on_one_line_and_long_json_per_item() -> None:
    assert call_api.render({"a": 1}) == '{"a": 1}'
    long_list = call_api.render(
        [{"name": "х" * 40}, {"name": "у" * 40}, {"name": "ф" * 40}]
    )
    assert long_list.startswith("[\n  {")
    assert long_list.count("\n") == 4
    long_object = call_api.render({"first": "а" * 70, "second": "б" * 70})
    assert long_object.splitlines()[1].startswith('  "first": ')


def test_call_api_tool_shows_request_status_and_body(
    server: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("STUDENT_API_URL", server)
    assert call_api.main(["GET", "/groups/1/statistics"]) == 0
    out = capsys.readouterr().out
    assert "> GET /groups/1/statistics" in out
    assert "< HTTP 200 OK" in out
    assert call_api.main(["POST", "/groups", "name=PI-21"]) == 1
    assert "< HTTP 409 Conflict" in capsys.readouterr().out


def test_call_api_tool_prints_usage_without_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert call_api.main([]) == 2
    assert "Використання" in capsys.readouterr().out


def test_call_api_tool_shows_location_and_total_count_headers(
    server: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("STUDENT_API_URL", server)
    body = [
        "first_name=Софія",
        "last_name=Гнатюк",
        "group_id:=1",
        "average_grade:=88",
    ]
    assert call_api.main(["POST", "/students", *body]) == 0
    created = capsys.readouterr().out
    assert "< HTTP 201 Created" in created
    assert "< Location: /students/2" in created
    assert call_api.main(["GET", "/students?limit=1"]) == 0
    listed = capsys.readouterr().out
    assert "< X-Total-Count: 2" in listed
    assert "< Location" not in listed
