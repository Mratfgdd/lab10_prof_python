"""Ручні HTTP-запити до API у стилі httpie."""

import json
import os
import sys
from collections.abc import Sequence
from typing import Any

import httpx

SHOWN_HEADERS = ("Location", "X-Total-Count")

USAGE = (
    "Використання: python tools/call_api.py METHOD PATH [поле=рядок] "
    "[поле:=JSON]\n"
    "  python tools/call_api.py POST /groups name=PI-21\n"
    "  python tools/call_api.py POST /students first_name=Олена "
    "last_name=Коваленко "
    "group_id:=1 average_grade:=95\n"
    "JSON-тіло збирається з аргументів. Базова адреса - змінна "
    "STUDENT_API_URL "
    "(типово http://127.0.0.1:8000)."
)


def parse_body(items: Sequence[str]) -> dict[str, Any] | None:
    """Збирає JSON-тіло з аргументів поле=рядок і поле:=JSON."""
    body: dict[str, Any] = {}
    for item in items:
        if ":=" in item:
            key, raw = item.split(":=", 1)
            body[key] = json.loads(raw)
        else:
            key, value = item.split("=", 1)
            body[key] = value
    return body or None


def render(data: Any, width: int = 140) -> str:
    """Друкує JSON: короткий - в один рядок, довгий - по рядку на поле."""
    compact = json.dumps(data, ensure_ascii=False)
    if len(compact) <= width:
        return compact
    if isinstance(data, list):
        items = [f"  {json.dumps(item, ensure_ascii=False)}" for item in data]
        return "[\n" + ",\n".join(items) + "\n]"
    if isinstance(data, dict):
        fields = [
            f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in data.items()
        ]
        return "{\n" + ",\n".join(fields) + "\n}"
    return compact


def main(argv: Sequence[str]) -> int:
    """Виконує запит і друкує статус, заголовки й тіло відповіді."""
    if len(argv) < 2:
        print(USAGE)
        return 2
    method, path, *items = argv
    body = parse_body(items)
    base_url = os.environ.get("STUDENT_API_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        response = client.request(method.upper(), path, json=body)
    request_line = f"{method.upper()} {path}"
    if body is not None:
        request_line += " " + json.dumps(body, ensure_ascii=False)
    print(f"> {request_line}")
    print(f"< HTTP {response.status_code} {response.reason_phrase}")
    for header in SHOWN_HEADERS:
        if header in response.headers:
            print(f"< {header}: {response.headers[header]}")
    if response.content:
        print(render(response.json()))
    return 0 if response.is_success else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
