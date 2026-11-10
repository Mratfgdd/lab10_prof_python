"""REST API: endpoints студентів і груп."""

from typing import Any

import httpx
import pytest

from student_manager import __version__

pytestmark = pytest.mark.asyncio

NEW_STUDENT = {
    "first_name": "Софія",
    "last_name": "Гнатюк",
    "group_id": 3,
    "average_grade": 88.0,
}


async def test_root_describes_the_service(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "service": "Student Manager API",
        "version": __version__,
        "docs": "/docs",
    }


async def test_list_is_empty_for_a_new_database(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/students")
    assert (response.status_code, response.json()) == (200, [])


async def test_list_returns_students_sorted_by_last_name(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get("/students")
    assert response.status_code == 200
    assert [s["last_name"] for s in response.json()] == [
        "Бондар",
        "Гриценко",
        "Коваленко",
        "Мельник",
    ]
    assert response.json()[0] == {
        "id": campus["Бондар"],
        "first_name": "Ірина",
        "last_name": "Бондар",
        "group_id": campus["PI-22"],
        "group_name": "PI-22",
        "average_grade": 99.5,
        "email": None,
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"last_name": "Мельник"}, ["Мельник"]),
        ({"last_name": "Ніхто"}, []),
        ({"min_grade": 90}, ["Бондар", "Коваленко"]),
        ({"max_grade": 80}, ["Гриценко", "Мельник"]),
        (
            {"min_grade": 55, "max_grade": 95},
            ["Гриценко", "Коваленко", "Мельник"],
        ),
        (
            {"sort": "average_grade", "order": "desc"},
            ["Бондар", "Коваленко", "Мельник", "Гриценко"],
        ),
        ({"sort": "average_grade", "limit": 2}, ["Гриценко", "Мельник"]),
        (
            {"sort": "average_grade", "limit": 2, "offset": 2},
            ["Коваленко", "Бондар"],
        ),
        ({"limit": 1, "offset": 10}, []),
    ],
    ids=[
        "by-last-name",
        "unknown-last-name",
        "min-grade",
        "max-grade",
        "grade-range",
        "sorted-desc",
        "first-page",
        "second-page",
        "page-beyond-end",
    ],
)
async def test_list_supports_filters_sorting_and_pagination(
    client: httpx.AsyncClient,
    campus: dict[str, int],
    params: dict[str, Any],
    expected: list[str],
) -> None:
    response = await client.get("/students", params=params)
    assert response.status_code == 200
    assert [s["last_name"] for s in response.json()] == expected


async def test_list_filters_by_group_id(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get(
        "/students", params={"group_id": campus["PI-21"]}
    )
    assert [s["last_name"] for s in response.json()] == [
        "Коваленко",
        "Мельник",
    ]


async def test_list_by_unknown_group_is_404(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get("/students", params={"group_id": 999})
    assert response.status_code == 404
    assert response.json() == {
        "error": "group_not_found",
        "detail": "групу з id=999 не знайдено",
    }


async def test_inverted_grade_range_is_422(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get(
        "/students", params={"min_grade": 90, "max_grade": 10}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "student_validation"


async def test_get_student_by_id(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get(f"/students/{campus['Коваленко']}")
    assert response.status_code == 200
    assert response.json()["email"] == "olena@example.com"


async def test_get_unknown_student_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/students/999")
    assert response.status_code == 404
    assert response.json() == {
        "error": "student_not_found",
        "detail": "студента з id=999 не знайдено",
    }


async def test_best_student_has_the_highest_average(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get("/students/best")
    assert response.status_code == 200
    assert (
        response.json()["last_name"],
        response.json()["average_grade"],
    ) == ("Бондар", 99.5)


async def test_best_student_of_empty_database_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/students/best")
    assert (response.status_code, response.json()["error"]) == (
        404,
        "student_not_found",
    )


async def test_create_student_returns_201_location_and_body(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.post(
        "/students", json={**NEW_STUDENT, "group_id": campus["PI-23"]}
    )
    assert response.status_code == 201
    created = response.json()
    assert response.headers["location"] == f"/students/{created['id']}"
    assert created["group_name"] == "PI-23"
    assert (await client.get(f"/students/{created['id']}")).json() == created


async def test_create_normalizes_names_and_email(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    body = {
        **NEW_STUDENT,
        "first_name": "  Софія ",
        "email": " Sofia@Example.COM ",
        "group_id": 1,
    }
    created = (await client.post("/students", json=body)).json()
    assert (created["first_name"], created["email"]) == (
        "Софія",
        "sofia@example.com",
    )


async def test_create_in_unknown_group_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/students", json=NEW_STUDENT)
    assert (response.status_code, response.json()["error"]) == (
        404,
        "group_not_found",
    )
    assert (await client.get("/students")).json() == []


async def test_create_with_duplicate_email_is_409(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    body = {**NEW_STUDENT, "group_id": 1, "email": "OLENA@example.com"}
    response = await client.post("/students", json=body)
    assert (response.status_code, response.json()["error"]) == (
        409,
        "duplicate_email",
    )
    assert len((await client.get("/students")).json()) == 4


async def test_patch_changes_only_the_given_field(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    before = (await client.get(f"/students/{campus['Мельник']}")).json()
    response = await client.patch(
        f"/students/{campus['Мельник']}", json={"average_grade": 85.5}
    )
    assert response.status_code == 200
    assert response.json() == {**before, "average_grade": 85.5}


async def test_patch_moves_the_student_to_another_group(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.patch(
        f"/students/{campus['Мельник']}",
        json={"group_id": campus["PI-23"], "average_grade": 70},
    )
    assert response.status_code == 200
    assert (
        response.json()["group_name"],
        response.json()["average_grade"],
    ) == ("PI-23", 70.0)
    stats = (await client.get(f"/groups/{campus['PI-23']}/statistics")).json()
    assert stats["students_count"] == 1


async def test_patch_can_set_and_clear_the_email(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    url = f"/students/{campus['Коваленко']}"
    assert (await client.patch(url, json={"email": None})).json()[
        "email"
    ] is None
    assert (await client.patch(url, json={"email": "new@example.com"})).json()[
        "email"
    ] == ("new@example.com")


async def test_patch_unknown_student_is_404(client: httpx.AsyncClient) -> None:
    response = await client.patch("/students/999", json={"average_grade": 50})
    assert response.status_code == 404


async def test_patch_with_unknown_group_changes_nothing(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    url = f"/students/{campus['Мельник']}"
    response = await client.patch(
        url, json={"average_grade": 10, "group_id": 999}
    )
    assert response.status_code == 404
    assert (await client.get(url)).json()["average_grade"] == 80.0


async def test_patch_with_duplicate_email_is_409(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.patch(
        f"/students/{campus['Мельник']}", json={"email": "olena@example.com"}
    )
    assert (response.status_code, response.json()["error"]) == (
        409,
        "duplicate_email",
    )


async def test_delete_returns_204_and_removes_the_student(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    url = f"/students/{campus['Гриценко']}"
    response = await client.delete(url)
    assert (response.status_code, response.content) == (204, b"")
    assert (await client.get(url)).status_code == 404
    assert len((await client.get("/students")).json()) == 3


async def test_delete_unknown_student_is_404(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.delete("/students/999")).status_code == 404


async def test_deleting_twice_gives_204_then_404(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    url = f"/students/{campus['Бондар']}"
    assert (await client.delete(url)).status_code == 204
    assert (await client.delete(url)).status_code == 404


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("мел", ["Мельник"]),
        ("БОН", ["Бондар"]),
        ("г", ["Гриценко"]),
        ("%", []),
        ("Ніхто", []),
    ],
)
async def test_last_name_is_a_case_insensitive_prefix_search(
    client: httpx.AsyncClient,
    campus: dict[str, int],
    prefix: str,
    expected: list[str],
) -> None:
    response = await client.get("/students", params={"last_name": prefix})
    assert response.status_code == 200
    assert [s["last_name"] for s in response.json()] == expected


@pytest.mark.parametrize(
    ("params", "total", "returned"),
    [
        ({}, 4, 4),
        ({"limit": 2}, 4, 2),
        ({"limit": 2, "offset": 3}, 4, 1),
        ({"limit": 1, "offset": 10}, 4, 0),
        ({"min_grade": 90}, 2, 2),
        ({"last_name": "м", "limit": 1}, 1, 1),
        ({"last_name": "Ніхто"}, 0, 0),
    ],
)
async def test_total_count_header_ignores_pagination_and_follows_filters(
    client: httpx.AsyncClient,
    campus: dict[str, int],
    params: dict[str, Any],
    total: int,
    returned: int,
) -> None:
    response = await client.get("/students", params=params)
    assert response.headers["x-total-count"] == str(total)
    assert len(response.json()) == returned


async def test_create_group_returns_201_and_empty_statistics(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/groups", json={"name": "PI-21"})
    assert response.status_code == 201
    assert response.json() == {
        "group_id": 1,
        "name": "PI-21",
        "students_count": 0,
        "average_grade": None,
        "best_grade": None,
        "worst_grade": None,
    }


async def test_duplicate_group_is_409(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.post("/groups", json={"name": "PI-21"})
    assert (response.status_code, response.json()["error"]) == (
        409,
        "duplicate_group",
    )


async def test_list_groups_contains_statistics_and_empty_groups(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get("/groups")
    assert response.status_code == 200
    summary = {g["name"]: g for g in response.json()}
    assert summary["PI-21"]["students_count"] == 2
    assert summary["PI-21"]["average_grade"] == 87.5
    assert summary["PI-23"]["students_count"] == 0
    assert summary["PI-23"]["average_grade"] is None


async def test_group_students_are_sorted_by_name(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get(f"/groups/{campus['PI-22']}/students")
    assert response.status_code == 200
    assert [s["last_name"] for s in response.json()] == ["Бондар", "Гриценко"]


async def test_students_of_an_empty_group_is_an_empty_list(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get(f"/groups/{campus['PI-23']}/students")
    assert (response.status_code, response.json()) == (200, [])


async def test_students_of_unknown_group_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/groups/999/students")
    assert (response.status_code, response.json()["error"]) == (
        404,
        "group_not_found",
    )


async def test_group_statistics(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.get(f"/groups/{campus['PI-22']}/statistics")
    assert response.status_code == 200
    assert response.json() == {
        "group_id": campus["PI-22"],
        "name": "PI-22",
        "students_count": 2,
        "average_grade": 77.25,
        "best_grade": 99.5,
        "worst_grade": 55.0,
    }


async def test_group_statistics_follow_changes(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    await client.patch(
        f"/students/{campus['Гриценко']}", json={"average_grade": 100}
    )
    stats = (await client.get(f"/groups/{campus['PI-22']}/statistics")).json()
    assert (stats["average_grade"], stats["worst_grade"]) == (99.75, 99.5)


async def test_statistics_of_unknown_group_is_404(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/groups/999/statistics")).status_code == 404


async def test_transfer_moves_students_in_one_transaction(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    target = campus["PI-23"]
    response = await client.post(
        f"/groups/{target}/transfer",
        json={
            "student_ids": [
                campus["Коваленко"],
                campus["Мельник"],
                campus["Мельник"],
            ]
        },
    )
    assert response.status_code == 200
    assert response.json() == {"group_id": target, "moved": 2}
    members = (await client.get(f"/groups/{target}/students")).json()
    assert [s["last_name"] for s in members] == ["Коваленко", "Мельник"]
    assert (
        await client.get(f"/groups/{campus['PI-21']}/students")
    ).json() == []


async def test_transfer_with_a_missing_student_rolls_everything_back(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    target = campus["PI-23"]
    response = await client.post(
        f"/groups/{target}/transfer",
        json={"student_ids": [campus["Коваленко"], 999]},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "student_not_found"
    assert (await client.get(f"/groups/{target}/students")).json() == []
    assert (
        len((await client.get(f"/groups/{campus['PI-21']}/students")).json())
        == 2
    )


async def test_transfer_to_unknown_group_is_404(
    client: httpx.AsyncClient, campus: dict[str, int]
) -> None:
    response = await client.post(
        "/groups/999/transfer", json={"student_ids": [1]}
    )
    assert (response.status_code, response.json()["error"]) == (
        404,
        "group_not_found",
    )


@pytest.mark.parametrize(
    "body", [{"student_ids": []}, {"student_ids": [0]}, {}, {"ids": [1]}]
)
async def test_transfer_validates_the_body(
    client: httpx.AsyncClient, campus: dict[str, int], body: dict[str, object]
) -> None:
    response = await client.post(
        f"/groups/{campus['PI-23']}/transfer", json=body
    )
    assert response.status_code == 422
