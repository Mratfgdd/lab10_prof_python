"""Мінімальний HTTP-клієнт для ручної перевірки API (у стилі httpie).

Назва не http.py: скрипт у tools/ з такою назвою затінив би стандартний пакет http,
і httpx не зміг би імпортувати http.client.

    python tools/call_api.py METHOD PATH [поле=рядок] [поле:=JSON]
    python tools/call_api.py POST /clients full_name="Олена Коваленко"
    python tools/call_api.py POST /accounts client_id:=1 number=UA-1001 opening_balance=1000

JSON-тіло збирається з аргументів: у Windows PowerShell 5.1 лапки всередині JSON-рядка
в аргументах програм губляться, тому писати '{"a": 1}' вручну незручно.
Базова адреса - змінна BANK_API_URL (типово http://127.0.0.1:8000).
"""

import json
import os
import sys
from collections.abc import Sequence
from typing import Any

import httpx


def parse_body(items: Sequence[str]) -> dict[str, Any] | None:
    body: dict[str, Any] = {}
    for item in items:
        if ":=" in item:
            key, raw = item.split(":=", 1)
            body[key] = json.loads(raw)
        else:
            key, value = item.split("=", 1)
            body[key] = value
    return body or None


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    method, path, *items = argv
    body = parse_body(items)
    base_url = os.environ.get("BANK_API_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        response = client.request(method.upper(), path, json=body)
    request_line = f"{method.upper()} {path}"
    if body is not None:
        request_line += " " + json.dumps(body, ensure_ascii=False)
    print(f"> {request_line}")
    print(f"< HTTP {response.status_code} {response.reason_phrase}")
    if response.content:
        print(render(response.json()))
    return 0 if response.is_success else 1


def render(data: Any, width: int = 110) -> str:
    """Короткий JSON - одним рядком; довгий - по рядку на поле або елемент списку."""
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
