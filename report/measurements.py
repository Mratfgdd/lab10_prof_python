"""Локальні перевірки для звіту: якість, збірка пакета, wheel-smoke."""

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from html_tools import CAPTURES, ROOT, last_line, run_program

WHEEL = "student_manager-1.0.0-py3-none-any.whl"
SDIST = "student_manager-1.0.0.tar.gz"


@dataclass
class Quality:
    """Результати lint, format, mypy, secret scan і pytest."""

    ruff: str
    format: str
    mypy: str
    secrets: str
    pytest: str
    passed: int
    percent: str


@dataclass
class Package:
    """Результати збірки пакета й запуску wheel."""

    build: str
    listing: str
    wheel_files: str
    metadata: str
    twine: str
    smoke: str


def program(venv: Path, name: str) -> str:
    """Шлях до програми в Scripts virtual environment."""
    return str(venv / "Scripts" / f"{name}.exe")


def output(command: list[str]) -> str:
    """Вивід команди; помилку перетворює на виняток."""
    done = run_program(command)
    if done.returncode:
        raise RuntimeError(f"{command}: {done.stdout}{done.stderr}")
    return (done.stdout + done.stderr).strip()


def quality(venv: Path) -> Quality:
    """Запускає ті самі перевірки, що й CI."""
    coverage = output(
        [
            str(venv / "Scripts" / "python.exe"),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov",
            "--cov-report=term-missing",
        ]
    )
    passed = re.search(r"(\d+) passed", coverage)
    total = re.search(r"Total coverage: ([\d.]+)%", coverage)
    if not passed or not total:
        raise RuntimeError(coverage)
    table = [
        line
        for line in coverage.splitlines()
        if line.startswith(("Name", "---", "src", "TOTAL", "Required"))
    ]
    return Quality(
        ruff=output([program(venv, "ruff"), "check", "."]),
        format=output([program(venv, "ruff"), "format", "--check", "."]),
        mypy=output([program(venv, "mypy")]),
        secrets=output(
            [str(venv / "Scripts" / "python.exe"), "tools/check_secrets.py"]
        ),
        pytest="\n".join([*table, last_line(coverage)]),
        passed=int(passed.group(1)),
        percent=total.group(1),
    )


def wheel_listing(path: Path) -> tuple[str, str]:
    """Вміст wheel (скорочено) і ключові рядки METADATA."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        meta_name = next(n for n in names if n.endswith("METADATA"))
        meta = archive.read(meta_name).decode("utf-8")
    keys = (
        "Name:",
        "Version:",
        "Summary:",
        "License-Expression:",
        "Requires-Python:",
    )
    lines = [
        line
        for line in meta.splitlines()
        if line.startswith(keys) and "extra ==" not in line
    ]
    interesting = [
        name
        for name in names
        if "migrations" in name
        or "static" in name
        or name.endswith(("py.typed", "LICENSE", "entry_points.txt"))
    ]
    return "\n".join(interesting), "\n".join(lines)


def package(venv: Path) -> Package:
    """Збирає wheel і sdist, перевіряє їх і запускає wheel у чистому venv."""
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    python = str(venv / "Scripts" / "python.exe")
    built = output([python, "-m", "build"])
    files, meta = wheel_listing(ROOT / "dist" / WHEEL)
    listing = output(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-ChildItem dist | "
            "Select-Object Name, Length | Format-Table -AutoSize | Out-String",
        ]
    )
    twine = output(
        [program(venv, "twine"), "check", "dist/" + WHEEL, "dist/" + SDIST]
    )
    smoke = output([python, "tools/smoke_test.py", "--wheel", "dist/" + WHEEL])
    return Package(
        build="\n".join(built.splitlines()[-2:]),
        listing=listing,
        wheel_files=files,
        metadata=meta,
        twine=twine,
        smoke=smoke,
    )


def load_ci() -> dict[str, Any]:
    """Зібрані докази GitHub Actions."""
    text = (CAPTURES / "ci.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data
