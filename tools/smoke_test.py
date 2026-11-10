"""Smoke-тест працюючого API: локальний запуск із wheel або готовий URL.

python tools/smoke_test.py --url http://127.0.0.1:8000 --token ...
    перевіряє вже запущений сервер (наприклад, Docker-контейнер);
python tools/smoke_test.py --wheel dist/student_manager-1.0.0-py3-none-any.whl
    створює чисте virtual environment, встановлює wheel, виконує міграції,
    запускає student-manager serve й перевіряє API.
Токен беруть зі змінної SMOKE_API_TOKEN або з аргументу --token.
"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def call(
    base: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, Any]:
    """HTTP-запит до API; повертає код відповіді та розібраний JSON."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-Key"] = token
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or "null")


def expect(label: str, actual: object, expected: object) -> None:
    """Друкує результат перевірки; при розбіжності завершує з кодом 1."""
    mark = "OK  " if actual == expected else "FAIL"
    print(f"{mark} {label}: {actual}")
    if actual != expected:
        raise SystemExit(1)


def exercise(base: str, token: str | None) -> None:
    """Сценарій: health, захист записів, створення даних, статистика."""
    code, health = call(base, "GET", "/health")
    expect("GET /health", (code, health["status"]), (200, "ok"))
    print(f"    {json.dumps(health, ensure_ascii=False)}")
    if token:
        code, _ = call(base, "POST", "/groups", {"name": "PI-31"})
        expect("POST /groups без X-API-Key", code, 401)
    code, group = call(base, "POST", "/groups", {"name": "PI-31"}, token)
    expect("POST /groups", code, 201)
    student = {
        "first_name": "Олена",
        "last_name": "Коваленко",
        "group_id": group["group_id"],
        "average_grade": 95.5,
    }
    code, created = call(base, "POST", "/students", student, token)
    expect("POST /students", code, 201)
    code, found = call(
        base, "GET", f"/students?last_name={urllib.parse.quote('Ковал')}"
    )
    expect("GET /students?last_name=", (code, len(found)), (200, 1))
    path = f"/groups/{group['group_id']}/statistics"
    code, stats = call(base, "GET", path)
    expect("GET " + path, (code, stats["students_count"]), (200, 1))
    code, members = call(base, "GET", f"/groups/{group['group_id']}/students")
    expect("GET /groups/{id}/students", (code, len(members)), (200, 1))
    code, _ = call(base, "DELETE", f"/students/{created['id']}", None, token)
    expect("DELETE /students/{id}", code, 204)
    code, docs = call(base, "GET", "/openapi.json")
    expect("GET /openapi.json", code, 200)
    print(f"    маршрутів в OpenAPI: {len(docs['paths'])}")


def check_persisted(base: str, group: str) -> None:
    """Група, створена до перезапуску, має лишитися в базі."""
    code, groups = call(base, "GET", "/groups")
    names = [item["name"] for item in groups]
    expect(
        f"група {group} збереглась після перезапуску",
        (code, group in names),
        (200, True),
    )


def free_port() -> int:
    """Вільний локальний порт."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def venv_program(venv: Path, name: str) -> str:
    """Шлях до програми в virtual environment (Windows або Linux)."""
    folder = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return str(venv / folder / (name + suffix))


def wait_for_health(base: str, timeout: float = 30.0) -> None:
    """Чекає, поки /health почне відповідати."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if call(base, "GET", "/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.3)
    raise SystemExit("сервер не відповів на /health")


def stop(server: "subprocess.Popen[bytes]") -> None:
    """Зупиняє сервер разом із дочірніми процесами (на Windows - taskkill)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(server.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        server.terminate()
    server.wait(timeout=15)


def run_wheel(wheel: Path) -> None:
    """Встановлює wheel у чистий venv і перевіряє застосунок."""
    token = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(
        prefix="student-manager-", ignore_cleanup_errors=True
    ) as folder:
        root = Path(folder)
        venv = root / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run(
            [venv_program(venv, "python"), "-m", "pip", "install", "-q"]
            + [str(wheel)],
            check=True,
        )
        env = {
            **os.environ,
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "INFO",
            "DATABASE_URL": f"sqlite:///{root / 'data' / 'students.db'}",
            "API_TOKEN": token,
        }
        program = venv_program(venv, "student-manager")
        print(
            subprocess.run(
                [program, "--version"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        print(
            subprocess.run(
                [program, "config"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.rstrip()
        )
        port = free_port()
        with subprocess.Popen(
            [program, "serve", "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as server:
            try:
                base = f"http://127.0.0.1:{port}"
                wait_for_health(base)
                exercise(base, token)
            finally:
                stop(server)
        print(f"БД збережена: {(root / 'data' / 'students.db').exists()}")


def main(argv: Sequence[str] | None = None) -> int:
    """Розбирає аргументи й виконує вибраний режим."""
    parser = argparse.ArgumentParser(description="Smoke-тест Student Manager")
    parser.add_argument("--url", help="адреса вже запущеного API")
    parser.add_argument("--token", default=os.environ.get("SMOKE_API_TOKEN"))
    parser.add_argument("--wheel", type=Path, help="wheel для чистого venv")
    parser.add_argument(
        "--persisted", metavar="GROUP", help="перевірити, що група є в базі"
    )
    args = parser.parse_args(argv)
    if args.wheel:
        run_wheel(args.wheel)
    elif args.url and args.persisted:
        wait_for_health(args.url)
        check_persisted(args.url, args.persisted)
    elif args.url:
        wait_for_health(args.url)
        exercise(args.url, args.token)
    else:
        parser.error("потрібен --url або --wheel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
