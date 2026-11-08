"""Аудит секретів: шукає у файлах проєкту значення, схожі на паролі, токени й ключі.

Запуск: python tools/check_secrets.py [каталог]. Код завершення 1, якщо є знахідки.
Перевіряються файли, що потрапляють у Git і Docker build context (без .venv, dist, .env).
Свідомо фальшиві значення в тестах позначаються коментарем «pragma: allowlist secret».
"""

import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "htmlcov",
    "static",
    "report",
}
SKIP_FILES = {".env"}
SUFFIXES = {".py", ".toml", ".ini", ".yml", ".yaml", ".md", ".cfg", ".txt", ".json", ".sh"}
NAMES = {"Dockerfile", ".env.example", ".dockerignore", ".gitignore"}
PATTERNS = {
    "присвоєння секрету": re.compile(
        r"""(?i)\b\w*(password|passwd|secret|token|api_?key)\w*\s*[:=]\s*["'][^"'\s]{4,}["']"""
    ),
    "секрет у .env-рядку": re.compile(r"""(?im)^\s*\w*(PASSWORD|SECRET|TOKEN|API_?KEY)\w*=\S+"""),
    "логін і пароль в URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@*]+@"),
    "приватний ключ": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "токен GitHub/AWS": re.compile(r"\b(ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
}
ALLOW = "pragma: allowlist secret"


def candidates(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts) or not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix in SUFFIXES or path.name in NAMES:
            files.append(path)
    return files


def scan(root: Path) -> tuple[int, list[str]]:
    files = candidates(root)
    findings = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ALLOW in line:
                continue
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{path.relative_to(root)}:{number}: {name}: {line.strip()}")
    return len(files), findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    checked, findings = scan(root)
    for finding in findings:
        print(finding)
    print(f"Перевірено файлів: {checked}; підозрілих рядків: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
