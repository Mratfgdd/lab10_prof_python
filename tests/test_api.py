"""API tests: HTTP methods, status codes, JSON, validation, зв'язок із persistence layer."""

import asyncio
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.asyncio

VARIANT_ENDPOINTS = {
    ("post", "/clients"),
    ("post", "/accounts"),
    ("get", "/accounts/{account_id}"),
    ("get", "/accounts/{account_id}/transactions"),
    ("post", "/accounts/{account_id}/deposit"),
    ("post", "/accounts/{account_id}/withdraw"),
    ("post", "/transfers"),
}


async def balance(client: httpx.AsyncClient, account_id: int) -> str:
    value: str = (await client.get(f"/accounts/{account_id}")).json()["balance"]
    return value


async def operations(client: httpx.AsyncClient, account_id: int) -> int:
    return len((await client.get(f"/accounts/{account_id}/transactions")).json())


async def test_openapi_lists_variant_endpoints_and_docs_work_offline(
    client: httpx.AsyncClient,
) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    documented = {(method, path) for path, item in paths.items() for method in item}
    assert VARIANT_ENDPOINTS <= documented
    docs = await client.get("/docs")
    assert docs.status_code == 200
    assert "/static/swagger-ui-bundle.js" in docs.text
    assert (await client.get("/static/swagger-ui-bundle.js")).status_code == 200


async def test_create_client_and_account(client: httpx.AsyncClient) -> None:
    created = await client.post("/clients", json={"full_name": "  Ірина Бондар "})
    assert created.status_code == 201
    assert created.json() == {"id": 1, "full_name": "Ірина Бондар"}
    response = await client.post(
        "/accounts", json={"client_id": 1, "number": "UA-1003", "opening_balance": "120000"}
    )
    assert response.status_code == 201
    account = response.json()
    assert account == {
        "id": 1,
        "number": "UA-1003",
        "client_id": 1,
        "currency": "UAH",
        "balance": "120000.00",
        "account_type": "current",
    }
    assert (await client.get(f"/accounts/{account['id']}")).json() == account
    assert (await client.get("/clients/1")).json()["full_name"] == "Ірина Бондар"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/clients", {"full_name": " "}),
        ("post", "/accounts", {"client_id": 1, "number": "1001"}),
        ("post", "/accounts", {"client_id": 1, "number": "UA-1009", "currency": "uah"}),
        ("post", "/accounts/1/deposit", {"amount": "0"}),
        ("post", "/accounts/1/deposit", {"amount": "-5"}),
        ("post", "/accounts/1/deposit", {"amount": "1.005"}),
        ("post", "/accounts/1/deposit", {"amount": "abc"}),
        ("patch", "/accounts/1", {"account_type": "gold"}),
        ("post", "/transfers", {"source_id": 1, "target_id": 1, "amount": "5"}),
        ("get", "/accounts/0", None),
    ],
    ids=[
        "blank-name",
        "bad-number",
        "bad-currency",
        "zero",
        "negative",
        "three-decimals",
        "not-a-number",
        "unknown-type",
        "same-account",
        "id-zero",
    ],
)
async def test_invalid_requests_are_rejected_with_422(
    client: httpx.AsyncClient, bank: dict[str, int], method: str, path: str, body: Any
) -> None:
    response = await client.request(method, path, json=body)
    assert response.status_code == 422
    assert await balance(client, bank["UA-1001"]) == "1000.00"


@pytest.mark.parametrize(
    ("method", "path", "body", "error"),
    [
        ("get", "/accounts/999", None, "account_not_found"),
        ("get", "/clients/999", None, "client_not_found"),
        ("post", "/accounts/999/deposit", {"amount": "1"}, "account_not_found"),
        ("post", "/accounts", {"client_id": 999, "number": "UA-1009"}, "client_not_found"),
    ],
    ids=["get-account", "get-client", "deposit", "account-for-unknown-client"],
)
async def test_unknown_resources_return_404(
    client: httpx.AsyncClient, method: str, path: str, body: Any, error: str
) -> None:
    response = await client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json()["error"] == error


async def test_duplicate_account_number_is_conflict(
    client: httpx.AsyncClient, bank: dict[str, int]
) -> None:
    response = await client.post(
        "/accounts", json={"client_id": bank["olena"], "number": "UA-1002"}
    )
    assert response.status_code == 409
    assert response.json() == {"error": "duplicate_account", "detail": "рахунок UA-1002 уже існує"}


async def test_deposit_and_withdraw(client: httpx.AsyncClient, bank: dict[str, int]) -> None:
    account = bank["UA-1002"]
    deposit = await client.post(f"/accounts/{account}/deposit", json={"amount": "100.50"})
    assert deposit.status_code == 201
    assert deposit.json()["balance_after"] == "350.50"
    withdrawal = await client.post(f"/accounts/{account}/withdraw", json={"amount": 350.5})
    assert (withdrawal.status_code, withdrawal.json()["balance_after"]) == (201, "0.00")
    assert await balance(client, account) == "0.00"


async def test_negative_balance_is_forbidden(
    client: httpx.AsyncClient, bank: dict[str, int]
) -> None:
    account = bank["UA-1002"]
    response = await client.post(f"/accounts/{account}/withdraw", json={"amount": "250.01"})
    assert response.status_code == 409
    assert response.json()["error"] == "insufficient_funds"
    assert await balance(client, account) == "250.00"
    assert await operations(client, account) == 1


async def test_transfer_moves_money_and_records_both_sides(
    client: httpx.AsyncClient, bank: dict[str, int]
) -> None:
    response = await client.post(
        "/transfers",
        json={"source_id": bank["UA-1001"], "target_id": bank["UA-1002"], "amount": "400"},
    )
    assert response.status_code == 201
    debit, credit = response.json()["debit"], response.json()["credit"]
    assert (debit["operation"], debit["balance_after"]) == ("transfer_out", "600.00")
    assert (credit["operation"], credit["balance_after"]) == ("transfer_in", "650.00")
    assert await balance(client, bank["UA-1001"]) == "600.00"
    assert await balance(client, bank["UA-1002"]) == "650.00"


@pytest.mark.parametrize(
    ("target", "amount", "status", "error"),
    [("UA-2001", "400", 422, "currency"), ("UA-1002", "1000.01", 409, "insufficient_funds")],
    ids=["currency-mismatch", "insufficient-funds"],
)
async def test_failed_transfer_changes_nothing(
    client: httpx.AsyncClient,
    bank: dict[str, int],
    target: str,
    amount: str,
    status: int,
    error: str,
) -> None:
    response = await client.post(
        "/transfers",
        json={"source_id": bank["UA-1001"], "target_id": bank[target], "amount": amount},
    )
    assert (response.status_code, response.json()["error"]) == (status, error)
    assert await balance(client, bank["UA-1001"]) == "1000.00"
    assert await operations(client, bank["UA-1001"]) == 1


async def test_history_query_parameters(client: httpx.AsyncClient, bank: dict[str, int]) -> None:
    account = bank["UA-1001"]
    for amount in ("10", "20", "30"):
        await client.post(f"/accounts/{account}/deposit", json={"amount": amount})
    await client.post(f"/accounts/{account}/withdraw", json={"amount": "5"})
    history = (await client.get(f"/accounts/{account}/transactions")).json()
    assert [t["operation"] for t in history] == ["deposit"] * 4 + ["withdraw"]
    deposits = await client.get(
        f"/accounts/{account}/transactions", params={"operation": "deposit", "limit": 2}
    )
    assert [t["amount"] for t in deposits.json()] == ["1000.00", "10.00"]


async def test_list_accounts_search_filter_sort_page(
    client: httpx.AsyncClient, bank: dict[str, int]
) -> None:
    async def numbers(**params: Any) -> list[str]:
        response = await client.get("/accounts", params=params)
        assert response.status_code == 200
        return [a["number"] for a in response.json()]

    assert await numbers() == ["UA-1001", "UA-1002", "UA-2001"]
    assert await numbers(number="UA-1002") == ["UA-1002"]
    assert await numbers(currency="UAH", sort="balance", order="desc") == ["UA-1001", "UA-1002"]
    assert await numbers(client_id=bank["olena"], account_type="savings") == ["UA-2001"]
    assert await numbers(min_balance="200", limit=1, offset=1) == ["UA-1002"]
    assert (await client.get("/accounts", params={"limit": 0})).status_code == 422


async def test_patch_and_delete_account(client: httpx.AsyncClient, bank: dict[str, int]) -> None:
    account = bank["UA-1002"]
    patched = await client.patch(f"/accounts/{account}", json={"account_type": "savings"})
    assert (patched.status_code, patched.json()["account_type"]) == (200, "savings")
    unchanged = await client.patch(f"/accounts/{account}", json={})
    assert unchanged.json()["account_type"] == "savings"

    not_empty = await client.delete(f"/accounts/{account}")
    assert (not_empty.status_code, not_empty.json()["error"]) == (409, "account_not_empty")
    await client.post(f"/accounts/{account}/withdraw", json={"amount": "250"})
    deleted = await client.delete(f"/accounts/{account}")
    assert (deleted.status_code, deleted.content) == (204, b"")
    assert (await client.get(f"/accounts/{account}")).status_code == 404


async def test_statistics_funds(client: httpx.AsyncClient, bank: dict[str, int]) -> None:
    funds = (await client.get("/statistics/funds")).json()
    assert funds["totals"] == [
        {"currency": "UAH", "total": "1250.00"},
        {"currency": "USD", "total": "100.00"},
    ]
    assert funds["by_client"][0] == {
        "client": "Олена Коваленко",
        "currency": "UAH",
        "accounts": 1,
        "total": "1000.00",
    }


async def test_concurrent_withdrawals_never_overdraw(client: httpx.AsyncClient) -> None:
    """10 одночасних списань по 100 з 500: сервіс виконується в кількох потоках паралельно."""
    await client.post("/clients", json={"full_name": "Test"})
    await client.post(
        "/accounts", json={"client_id": 1, "number": "UA-5000", "opening_balance": "500"}
    )
    responses = await asyncio.gather(
        *(client.post("/accounts/1/withdraw", json={"amount": "100"}) for _ in range(10))
    )
    assert {r.status_code for r in responses} <= {201, 409}
    succeeded = sum(r.status_code == 201 for r in responses)
    assert 1 <= succeeded <= 5
    assert await balance(client, 1) == f"{500 - 100 * succeeded}.00"
    assert await operations(client, 1) == 1 + succeeded
