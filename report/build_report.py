"""Генерує звіт ЛР10 у PDF: HTML -> Microsoft Edge (headless) -> PDF.

Запуск з каталогу Lab_10 після report/capture.py:
    .venv\\Scripts\\python report\\build_report.py
Термінали - з report/captures/ (build, локальний прогін CI, Linux-перевірка) і живого запуску
tools/check_secrets.py; код - безпосередньо з файлів проєкту.
"""

import argparse
import ast
import base64
import html
import json
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "report"
CAPTURES = REPORT_DIR / "captures"
PDF_PATH = ROOT / "Звіт_ЛР10_Левандівський.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
WIN = r"PS C:\Github\prof_python\Lab_10>"
LINUX = "user@DESKTOP-J5SKKVH:~/bank$"
CI = "$"
SRC = ROOT / "src" / "bank_account_service"
MARK = re.compile(r"^::(step|ok|fail|skip)::(.*?)::(\d+)$")


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def code(source: str, keep: bool | None = None, cls: str = "") -> str:
    text = source.strip("\n")
    if keep is None:
        keep = text.count("\n") < 18
    return f'<pre class="code{" keep" if keep else ""} {cls}">{esc(text)}</pre>'


def _find(tree: ast.Module, name: str) -> ast.AST:
    scope: list[ast.stmt] = tree.body
    node: ast.stmt | None = None
    for piece in name.split("."):
        node = next(n for n in scope if getattr(n, "name", None) == piece)
        scope = getattr(node, "body", [])
    assert node is not None
    return node


def extract(path: Path, *names: str) -> str:
    """Код функцій/класів з декораторами - без імпорту модуля."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    parts = []
    for name in names:
        node = _find(tree, name)
        decorators = getattr(node, "decorator_list", [])
        start = min([d.lineno for d in decorators] + [node.lineno])  # type: ignore[attr-defined]
        parts.append(textwrap.dedent("\n".join(lines[start - 1:node.end_lineno])))  # type: ignore[attr-defined]
    return "\n\n".join(parts)


def terminal(*steps: tuple[str, str], prompt: str = WIN, split: bool = False) -> str:
    body = "\n".join(f'<span class="ps">{esc(prompt)}</span> {esc(command)}'
                     + (f"\n{esc(output.rstrip())}" if output.strip() else "")
                     for command, output in steps)
    return f'<div class="term{" split" if split else ""}">{body}</div>'


def excerpt(text: str, *prefixes: str) -> str:
    """Фрагмент виводу: рядки з цими префіксами, «…» на місці кожної пропущеної ділянки."""
    shown: list[str] = []
    for line in text.splitlines():
        if line.startswith(prefixes):
            shown.append(line)
        elif not shown or shown[-1] != "…":
            shown.append("…")
    return "\n".join(shown)


def figure(content: str, caption: str, split: bool = False) -> str:
    return f'<div class="figure{" split" if split else ""}">{content}{caption}</div>'


def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


class Numbering:
    def __init__(self) -> None:
        self.table = 0
        self.figure = 0

    def tcap(self, text: str) -> str:
        self.table += 1
        return f'<p class="tcap">Таблиця {self.table} – {text}</p>'

    def fcap(self, text: str) -> str:
        self.figure += 1
        return f'<p class="fcap">Рисунок {self.figure} – {text}</p>'


def load(name: str) -> Any:
    return json.loads((CAPTURES / name).read_text(encoding="utf-8"))


def ci_steps(log: str) -> dict[str, dict[str, Any]]:
    """Кроки з журналу tools/ci_local.py: статус, тривалість, вивід."""
    steps: dict[str, dict[str, Any]] = {}
    buffer: list[str] = []
    for line in log.splitlines():
        match = MARK.match(line.strip())
        if not match:
            buffer.append(line)
            continue
        kind, name, millis = match.groups()
        if kind == "step":
            buffer = []
        else:
            steps[name] = {"status": kind, "ms": int(millis), "out": "\n".join(buffer)}
    return steps


def linux_step(steps: list[dict[str, Any]], prefix: str) -> tuple[str, str]:
    step = next(s for s in steps if s["cmd"].startswith(prefix))
    return step["cmd"], step["out"]


def edge(*args: str) -> None:
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", *args],
                   check=True, capture_output=True, timeout=120)


CSS = """
@page { size: A4; margin: 20mm 15mm 20mm 30mm;
  @bottom-center { content: counter(page); font: 12pt "Times New Roman", serif; } }
@page :first { @bottom-center { content: none; } }
html { background: #fff; }
body { margin: 0; color: #000; background: #fff; font-family: "Times New Roman", serif;
  font-size: 14pt; line-height: 1.22; }
p { margin: 0 0 2pt; text-indent: 1.25cm; text-align: justify; }
h1 { font-size: 14pt; text-align: center; margin: 9pt 0 4pt; break-after: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.8em; }
pre.code { font-family: Consolas, "Courier New", monospace; font-size: 7.3pt;
  line-height: 1.12; margin: 2pt 0 5pt; padding: 3pt 8pt; white-space: pre-wrap;
  background: #f6f6f4; border-left: 3px solid #c3c2b7; orphans: 4; widows: 4; }
pre.keep { break-inside: avoid; }
pre.cols { column-count: 2; column-gap: 14pt; }
pre.cols4 { column-count: 4; column-gap: 10pt; }
ul { margin: 0 0 2pt; padding-left: 1.25cm; }
li { margin: 0; text-align: justify; }
.term { font-family: Consolas, "Courier New", monospace; font-size: 7pt; line-height: 1.13;
  white-space: pre-wrap; background: #0c0c0c; color: #d4d4d4; padding: 4pt 8pt;
  border-radius: 4px; margin: 2pt 0 3pt; break-inside: avoid; text-align: left; }
.term .ps { color: #f9f1a5; }
.term.split { break-inside: auto; orphans: 6; widows: 6; }
table { width: 100%; border-collapse: collapse; font-size: 10.5pt; line-height: 1.13;
  margin: 2pt 0 5pt; }
th, td { border: 1px solid #000; padding: 1.5pt 4pt; vertical-align: top; text-align: left; }
th { background: #f0efec; }
td code { font-size: 0.85em; }
tr { break-inside: avoid; }
table.keep { break-inside: avoid; }
.tcap { text-indent: 0; text-align: left; margin: 4pt 0 2pt; break-after: avoid; }
.fcap { text-indent: 0; text-align: center; margin: 1pt 0 5pt; }
.figure { break-inside: avoid; margin-top: 3pt; text-align: center; }
.figure.split { break-inside: auto; }
.fcap { break-before: avoid; }
.figure img { border: 1px solid #c3c2b7; }
.title { height: 255mm; display: flex; flex-direction: column; justify-content: space-between;
  text-align: center; break-after: page; line-height: 1.5; }
.title .main { margin-top: 30mm; }
.title .main .big { font-size: 20pt; font-weight: bold; letter-spacing: 2pt; }
.title .main .theme { font-size: 16pt; font-weight: bold; margin-top: 10pt; }
.title .sign { align-self: flex-end; text-align: left; width: 85mm; margin-top: 30mm; }
.title .city { margin-top: auto; }
"""

TREE = """Lab_10/
├── pyproject.toml          метадані пакета, залежності, ruff, mypy, pytest, coverage
├── README.md, LICENSE      документація, ліцензія MIT
├── .env.example            перелік змінних середовища без секретів
├── .gitignore, .dockerignore
├── Dockerfile              двоетапна збірка, non-root, HEALTHCHECK, volume /app/data
├── alembic.ini             міграції для розробки (alembic revision/upgrade)
├── .github/workflows/ci.yml
├── src/bank_account_service/
│   ├── __init__.py         __version__ з метаданих пакета;  py.typed
│   ├── main.py             CLI bank-account-service: serve, migrate, config, --version
│   ├── config.py           Settings (pydantic-settings): environment, .env, SecretStr
│   ├── api.py              FastAPI: REST API ЛР8, /health, X-API-Key, Swagger без CDN
│   ├── database.py         engine, сесії, перевірка схеми, міграції з пакета
│   ├── models.py, repositories.py, services.py, schemas.py, value_objects.py,
│   │   exceptions.py       предметна логіка й persistence (ЛР2–ЛР7)
│   ├── interest.py         прогноз відсотків на NumPy (оптимізація з ЛР9)
│   ├── external_api.py     асинхронний клієнт bank-api-client (ЛР8)
│   ├── migrations/         Alembic: env.py, versions/0001, 0002 (ЛР7)
│   └── static/             Swagger UI (js, css)
├── tests/                  52 тести: API, клієнт, конфігурація, health, секрети, CLI
└── tools/                  check_secrets.py, ci_local.py, call_api.py"""

COMMANDS = """# збірка образу і перегляд
docker build -t bank-account-service:1.0.0 .
docker images bank-account-service

# запуск: порт, volume для SQLite, конфігурація через -e та --env-file (секрет лише у .env)
docker run -d --name bank -p 8000:8000 \\
    -v bank_data:/app/data \\
    -e APP_ENV=production -e LOG_LEVEL=INFO \\
    --env-file .env \\
    bank-account-service:1.0.0
docker ps                      # STATUS: Up ... (healthy) після HEALTHCHECK
curl http://localhost:8000/health"""


def build_html() -> str:  # noqa: PLR0915
    n = Numbering()
    build = load("build.json")
    ci = load("ci.json")
    linux: list[dict[str, Any]] = load("linux.json")
    swagger = base64.b64encode((CAPTURES / "swagger.png").read_bytes()).decode()

    (log_name, log), = ci["logs"].items()
    steps = ci_steps(log)
    python_ci = re.search(r"py(\d\.\d+)", log_name)
    assert python_ci
    quality_ok = [name for name, s in steps.items() if s["status"] == "ok"]
    skipped = [name for name, s in steps.items() if s["status"] == "skip"]
    assert not [name for name, s in steps.items() if s["status"] == "fail"], steps
    assert skipped == ["Upload package artifact"], skipped
    pytest_out = steps["Tests with coverage (fail under 85 %)"]["out"]
    passed = re.search(r"(\d+) passed in ([\d.]+)s", pytest_out)
    coverage = re.search(r"Total coverage: ([\d.]+)%", pytest_out)
    assert passed and coverage
    secrets_run = subprocess.run([str(PYTHON), "tools/check_secrets.py"], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8", check=True)
    shutil.rmtree(ROOT / "tools" / "__pycache__", ignore_errors=True)

    build_lines = [excerpt(build["build"], "* Building", "Successfully")]
    wheel_files = [line.split()[0] for line in build["wheel"].splitlines()[1:] if line.strip()]
    sdist_files = [line for line in build["sdist"].splitlines() if not line.endswith("/")]
    meta = build["metadata"].split("\n\n", 1)[0].splitlines()
    meta_shown = [line for line in meta if line.split(":")[0] in (
        "Metadata-Version", "Name", "Version", "Summary", "Author", "License-Expression",
        "Requires-Python", "Requires-Dist")][:15]

    parts: list[str] = []
    add = parts.append
    add("""
<section class="title">
  <div>МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ<br>
  Львівський національний університет імені Івана Франка</div>
  <div class="main">
    <div class="big">ЗВІТ</div>
    <div>до лабораторної роботи №10</div>
    <div>з дисципліни «Професійний Python»</div>
    <div class="theme">Тема: «Production Python: Docker, CI/CD та захист проєкту»</div>
  </div>
  <div class="sign">Виконав:<br>студент Левандівський Назар<br><br>
  Перевірив:<br>Куньо Іван Михайлович</div>
  <div class="city">Львів – 2026</div>
</section>""")

    add("<h1>Мета роботи</h1>")
    add("<p>Підготувати проєкт до production-oriented використання: оформити його як "
        "installable package з <code>pyproject.toml</code>, зібрати wheel і sdist, винести "
        "конфігурацію в environment variables і прибрати secrets з коду, створити Dockerfile "
        "та .dockerignore, налаштувати CI/CD pipeline у GitHub Actions з автоматичними lint, "
        "type checking, tests і build, оформити документацію для фінального захисту.</p>")

    add("<h1>1. Варіант і опис проєкту</h1>")
    add("<p><b>Варіант 4. Система банківських рахунків.</b> Це завершальна версія проєкту "
        "ЛР1–ЛР9: пакет <code>bank-account-service</code> / <code>bank_account_service</code>. "
        "REST API з ЛР8 збережено: клієнти, рахунки, поповнення, списання, пошук і "
        "фільтри, історія операцій, загальна сума коштів, атомарний переказ без від'ємного "
        "балансу. Persistence – SQLite, SQLAlchemy 2 і міграції Alembic з ЛР7. З ЛР9 "
        "залишено NumPy-векторизацію нарахування відсотків, яка дала найбільше "
        "прискорення: вона працює в ендпоінті прогнозу <code>/statistics/interest</code>. "
        "У ЛР10 додано конфігурацію через environment, <code>GET /health</code>, захист "
        "змін даних ключем <code>X-API-Key</code>, CLI <code>bank-account-service</code>, "
        "автоматичні міграції під час запуску, Dockerfile, CI workflow і README.</p>")
    add(code(TREE, keep=True))

    add("<h1>2. Packaging: pyproject.toml, wheel і sdist</h1>")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").split("[tool.pytest")[0]
    add(code(project, keep=False, cls="cols"))
    add("<p>Версія 1.0.0 – за SemVer (MAJOR.MINOR.PATCH): перший стабільний реліз. "
        "<code>__version__</code> читається з метаданих встановленого пакета "
        "(<code>importlib.metadata</code>), тому версія записана лише в одному місці. "
        "Пакет має дві команди (<code>project.scripts</code>):</p>"
        "<ul>"
        "<li><code>bank-account-service</code> – запуск, міграції, конфігурація;</li>"
        "<li><code>bank-api-client</code> – асинхронний клієнт.</li>"
        "</ul>"
        "<p>Міграції Alembic і статичні файли Swagger UI входять у wheel як package data, "
        "тому встановлений пакет працює без вихідного коду проєкту.</p>")
    add(figure(terminal(("python -m build", "\n".join(build_lines)), ("Get-ChildItem dist",
                                                                    build["dist"].strip())),
               n.fcap("Збірка wheel і sdist (python -m build, фрагмент виводу) та вміст "
                      "каталогу dist")))
    build_figure = n.figure
    add(f"<p>Wheel містить {len(wheel_files)} файлів: модулі пакета, міграції, "
        "<code>static/</code>, <code>py.typed</code> і <code>dist-info</code> (METADATA, "
        "entry_points.txt, licenses/LICENSE). Sdist "
        f"(<code>.tar.gz</code>, {len(sdist_files)} файлів) містить вихідний код, тести, "
        "README, LICENSE і <code>pyproject.toml</code>, тобто з нього можна повторити "
        "build. Метадані пакета з wheel (фрагмент METADATA):</p>")
    add(code("\n".join(meta_shown), keep=True, cls="cols"))

    add("<h1>3. Конфігурація через environment і робота із secrets</h1>")
    add(n.tcap("Змінні середовища застосунку"))
    add(table(["Змінна", "Типово", "Призначення"], [
        ["<code>APP_ENV</code>", "development", "development, test або production (Docker: "
         "production)"],
        ["<code>DATABASE_URL</code>", "sqlite:///bank.db", "URL бази SQLAlchemy (Docker: "
         "sqlite:////app/data/bank.db у volume)"],
        ["<code>LOG_LEVEL</code>", "INFO", "DEBUG, INFO, WARNING, ERROR"],
        ["<code>CONFLICT_RETRIES</code>", "3", "повтори операції при конфлікті версій, 0–10"],
        ["<code>APP_NAME</code>", "Bank Account Service", "назва в логах і Swagger"],
        ["<code>API_TOKEN</code>", "не задано", "<b>secret</b>: якщо задано, POST, PATCH і "
         "DELETE вимагають заголовок <code>X-API-Key</code>"],
    ]))
    add("<p><code>Settings</code> (pydantic-settings) читає змінні середовища, а для "
        "локальної розробки – файл <code>.env</code>; змінна середовища має пріоритет над "
        "<code>.env</code>. Значення перевіряються під час старту: недопустимий "
        "<code>APP_ENV</code> чи від'ємний <code>CONFLICT_RETRIES</code> зупиняють сервіс з "
        "помилкою, а не приводять до некоректної роботи.</p>")
    add(code(extract(SRC / "config.py", "Settings", "get_settings")))
    add(code((ROOT / ".env.example").read_text(encoding="utf-8"), keep=True))
    add("<p><b>Secrets.</b> У коді, README, Dockerfile і Git немає жодного справжнього "
        "пароля чи токена. Секрет <code>API_TOKEN</code> надходить лише із середовища: з "
        "файлу <code>.env</code>, з <code>docker run --env-file</code> або з GitHub Actions "
        "secrets. <code>.env</code> внесено в <code>.gitignore</code> і "
        "<code>.dockerignore</code>, тож він не потрапляє ні в репозиторій, ні в образ. Тип "
        "<code>SecretStr</code> не показує значення в repr і логах, пароль у "
        "<code>DATABASE_URL</code> маскується в лозі запуску, а команда <code>config</code> "
        "показує конфігурацію з прихованими секретами. Ключ <code>X-API-Key</code> із "
        "запиту порівнюється через <code>secrets.compare_digest</code>, тобто за сталий "
        "час. Сканер <code>tools/check_secrets.py</code> є кроком CI і шукає в проєкті "
        "присвоєння паролів і токенів, credentials в URL, приватні ключі й токени "
        "GitHub/AWS.</p>")
    add(figure(terminal(("python tools/check_secrets.py", secrets_run.stdout))
               + terminal(linux_step(linux, "bank-account-service config"), prompt=LINUX),
               n.fcap("Перевірка проєкту на secrets і конфігурація сервісу з прихованим "
                      "API_TOKEN")))

    add("<h1>4. Docker: Dockerfile, .dockerignore, запуск контейнера</h1>")
    add(code((ROOT / "Dockerfile").read_text(encoding="utf-8")))
    add("<p>Образ двоетапний (multi-stage). Етап <code>builder</code> збирає wheel, і "
        "інструменти збірки до фінального образу не потрапляють. Runtime-етап на базі "
        "<code>python:3.12-slim</code> встановлює лише wheel і його залежності. Процес "
        "працює від користувача <code>appuser</code>, не від root. SQLite-файл лежить у "
        "volume <code>/app/data</code> і переживає перезапуск та оновлення контейнера. "
        "<code>HEALTHCHECK</code> кожні 30 с перевіряє <code>/health</code>. Команда "
        "<code>serve</code> спершу застосовує міграції (автоматичні міграції при "
        "deployment), а потім запускає uvicorn у production-режимі, без "
        "<code>--reload</code>. <code>.dockerignore</code> залишає в build context лише "
        "<code>pyproject.toml</code>, README, LICENSE і <code>src/</code>, тобто без "
        "<code>.env</code>, тестів, кешів і <code>.git</code>; секретів в образі немає, "
        "вони передаються під час запуску.</p>")
    dockerignore = "\n".join(line for line in (ROOT / ".dockerignore").read_text(
        encoding="utf-8").splitlines() if line and not line.startswith("#"))
    add(code("# .dockerignore\n" + dockerignore, keep=True, cls="cols4"))
    add(code(COMMANDS, keep=True))
    add("<p><b>Обмеження.</b> На ПК, де виконувалася робота, Docker не встановлено: у "
        "WSL Debian його немає, а для встановлення бракує прав адміністратора. Тому "
        "команди <code>docker build</code> і <code>docker run</code> не виконувалися, і "
        "знімків <code>docker images</code> та <code>docker ps</code> у звіті немає.</p>"
        "<p>Runtime-етап образу перевірено без Docker, тими самими кроками, що й у "
        "Dockerfile: wheel з <code>dist/</code> встановлено в нове venv у Linux (WSL "
        "Debian), змінні задано як <code>ENV</code> і <code>--env-file</code>, сервіс "
        "запущено командою з <code>CMD</code>, стан перевірено командою з "
        "<code>HEALTHCHECK</code>. Відмінності від образу: Python 3.13 замість 3.12, каталог "
        "<code>~/bank/data</code> замість volume, звичайний користувач WSL замість "
        "<code>appuser</code>.</p>")
    first = [linux_step(linux, prefix) for prefix in (
        "python3 -m venv", "pip install", "bank-account-service --version",
        "export APP_ENV", "set -a", "bank-account-service serve --host", "cat serve.log",
        "python -c")]
    add(figure(terminal(*first, prompt=LINUX),
               n.fcap("Wheel у чистому venv (Linux), конфігурація як у Dockerfile, запуск "
                      "CMD і перевірка HEALTHCHECK (exit code 0)")))
    api_steps = [linux_step(linux, prefix) for prefix in (
        "curl -s localhost:8000/health", "curl -s -w", "api() {",
        "api -X POST localhost:8000/clients -d '{\"full_name\": \"Олена",
        "api -X POST localhost:8000/accounts -d '{\"client_id\": 1",
        "api -X POST localhost:8000/accounts/1/deposit",
        "api -X POST localhost:8000/transfers -d '{\"source_id\": 1",
        "api -X POST localhost:8000/transfers -d '{\"source_id\": 2",
        "curl -s 'localhost:8000/statistics/interest")]
    add(figure(terminal(*api_steps, prompt=LINUX, split=True),
               n.fcap("Результат /health і робота API: без X-API-Key зміни заборонені (401), "
                      "з ключем – 201; переказ понад баланс – 409"), split=True))
    stopped = linux_step(linux, "kill $SERVER_PID; wait $SERVER_PID; tail")[1]
    reread = linux_step(linux, "curl -s 'localhost:8000/accounts?sort")[1]
    listing = linux_step(linux, "kill $SERVER_PID; wait $SERVER_PID; ls")[1]
    assert "Bank Account Service stopped" in stopped
    assert '"balance":"1200.00"' in reread and '"balance":"550.00"' in reread
    db_size = re.search(r"\s(\d+) \w{3}\s+\d+ [\d:]+ bank\.db", listing)
    assert db_size
    add("<p>Після <code>kill</code> (SIGTERM) сервіс завершився штатно: lifespan закрив "
        "пул з'єднань (у лозі «Bank Account Service stopped»). Після повторного запуску "
        "<code>GET /accounts</code> повернув ті самі рахунки з балансами 1200.00 і 550.00 "
        f"UAH: дані збереглися у файлі <code>data/bank.db</code> ({int(db_size.group(1)) // 1024}"
        " КБ), як у volume контейнера.</p>")
    add(figure(f'<img src="data:image/png;base64,{swagger}" alt="Swagger UI" '
               'style="width: 44%">',
               n.fcap("Swagger UI (/docs) сервісу, запущеного з wheel: розділ service з "
                      "/health і кнопка Authorize для X-API-Key")))

    add("<h1>5. CI/CD: GitHub Actions</h1>")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    add("<p>Workflow <code>.github/workflows/ci.yml</code> запускається на кожен push у "
        "<code>main</code>, на pull request і вручну. Права обмежено: "
        "<code>contents: read</code>. Він має два jobs:</p>"
        "<ul>"
        "<li><code>quality</code> – матриця Python 3.11 і 3.12;</li>"
        "<li><code>docker</code> – запускається лише після успішного "
        "<code>quality</code> (<code>needs</code>); збирає образ із тегами "
        "<code>ci</code> і коротким SHA commit, запускає контейнер і чекає відповіді "
        "<code>/health</code> (smoke test).</li>"
        "</ul>"
        "<p>Секрет береться з налаштувань репозиторію (<code>${{ secrets.API_TOKEN }}</code>) "
        "і передається в контейнер як <code>-e API_TOKEN</code> без значення в "
        "команді.</p>")
    yaml_part = (workflow[:workflow.index("      - name: Checkout")]
               + "      ...            # кроки job quality - у таблиці 2 і на рисунку "
               + str(n.figure + 1) + "\n\n" + workflow[workflow.index("  docker:"):
                                                     workflow.index("      - name: Remove")])
    add(code("# ci.yml (фрагмент, без коментарів)\n" + "\n".join(
        line for line in yaml_part.splitlines()
        if not line.lstrip().startswith("# ") or "кроки job" in line), keep=False))
    add("<p>GitHub Actions на GitHub не запускався, бо проєкт не публікувався в "
        "репозиторії на GitHub, тому знімка «зеленого» pipeline немає. Workflow "
        "перевірено скриптом <code>tools/ci_local.py</code>. Він читає <code>ci.yml</code> "
        "і виконує ті самі кроки <code>run</code> у чистому Linux-середовищі: свіжа копія "
        "проєкту без кешів і <code>.venv</code>, нове venv, встановлення з "
        "<code>pyproject.toml</code>. Python у WSL – " + python_ci.group(1) + ", тоді як "
        "у матриці – 3.11 і 3.12; на Windows тести пройшли на Python 3.12. Job "
        "<code>docker</code> пропущено, бо Docker на ПК немає.</p>")
    rows = []
    for name, step in steps.items():
        status = {"ok": "✓ успішно", "fail": "✗ помилка",
                  "skip": "– пропущено (if: лише Python 3.12)"}[step["status"]]
        rows.append([name, status, f"{step['ms'] / 1000:.1f}" if step["ms"] else "–"])
    docker_steps = [line.split(":", 1)[1].strip()
                    for line in workflow[workflow.index("  docker:"):].splitlines()
                    if line.strip().startswith("- name:")]
    rows.append([f"job docker: {', '.join(docker_steps)}", "– пропущено (немає Docker)", "–"])
    add(n.tcap(f"Кроки workflow у локальному прогоні (Linux, Python {python_ci.group(1)})"))
    add(table(["Крок", "Результат", "Час, с"], rows))
    pytest_lines = pytest_out.splitlines()
    total_line = next(line for line in pytest_lines if line.startswith("TOTAL"))
    header = next(line for line in pytest_lines if line.startswith("Name "))
    pytest_tail = "\n".join([header, "…", total_line, *pytest_lines[-3:]])
    ci_shown = [
        ("python tools/check_secrets.py", steps["Secret scan"]["out"]),
        ("ruff check .", steps["Ruff lint"]["out"]),
        ("ruff format --check .", steps["Ruff format check"]["out"]),
        ("mypy", steps["Type check (mypy --strict)"]["out"]),
        ("pytest -v --cov --cov-report=term-missing",
         "\n".join(pytest_out.splitlines()[:3]) + "\n…\n" + pytest_tail.strip()),
        ("python -m build", excerpt(steps["Build wheel and sdist"]["out"], "* Building",
                                    "Successfully")),
        ("ls -la dist", steps["Check dist"]["out"]),
        ("/tmp/wheel-env/bin/bank-account-service --version",
         steps["Install wheel in clean venv"]["out"].strip().splitlines()[-1]),
    ]
    add(figure(terminal(*ci_shown, prompt=CI, split=True),
               n.fcap(f"Lint, format, mypy, pytest ({passed.group(1)} тести, покриття "
                      f"{coverage.group(1)} % при порозі 85 %) і build у локальному прогоні "
                      "job quality (фрагменти виводу)"), split=True))
    add("<p>Локальний прогін виявив реальну помилку, якої не було видно на Windows: на "
        "Python 3.13 приблизно кожен четвертий запуск тестів падав з "
        "<code>ResourceWarning: unclosed database</code>. Причина була в клієнті з ЛР8: "
        "<code>asyncio.gather</code> після відповіді 404 на один запит рахунку лишав "
        "другий запит працювати після повернення результату. Його обробку на сервері "
        "скасовували вже після закриття пулу з'єднань, а синхронна yield-залежність "
        "FastAPI при скасуванні не закриває сесію. Виправлення: у клієнті "
        "<code>asyncio.TaskGroup</code>, який скасовує сусідній запит і чекає його "
        "завершення; на сервері асинхронна залежність, що закриває сесію в "
        "<code>finally</code>; <code>try/finally</code> у lifespan. Після виправлення 25 "
        "повторних прогонів пройшли без помилок.</p>")

    add("<h1>6. Документація, Git і production checklist</h1>")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = [line[3:] for line in readme.splitlines() if line.startswith("## ")]
    add("<p><b>README.md</b> має розділи " + ", ".join(headings) + ". Він описує "
        "предметну систему, встановлення (venv або wheel), таблицю змінних середовища, "
        "локальний запуск і запуск у Docker (з volume і <code>--env-file</code>), таблицю "
        "ендпоінтів, тести, CI/CD і сценарій демонстрації для захисту. Документацію API "
        "також генерує FastAPI: <code>/docs</code> (Swagger UI) і "
        "<code>/openapi.json</code>. Модулі й основні функції мають docstrings, а логування "
        "працює через <code>logging</code> з рівнем із <code>LOG_LEVEL</code>, без "
        "<code>print</code>.</p>")
    add("<p><b>Git.</b> Commits у межах цієї роботи не створювалися. Зміни варто "
        "оформити такими логічними commits:</p>")
    add(n.tcap("Плановий поділ змін на commits"))
    add(table(["Commit", "Файли"], [
        ["Add production configuration", "config.py, main.py, .env.example, /health, X-API-Key"],
        ["Add Python packaging", "pyproject.toml, LICENSE, __init__.py (__version__), py.typed"],
        ["Add Docker support", "Dockerfile, .dockerignore"],
        ["Add CI pipeline", ".github/workflows/ci.yml, tools/check_secrets.py, tools/ci_local.py"],
        ["Fix session leak on cancelled requests", "api.py (get_service, lifespan), "
         "external_api.py (TaskGroup)"],
        ["Add project documentation", "README.md"],
        ["Prepare release 1.0.0", "версія 1.0.0, тег v1.0.0"],
    ], cls="keep"))
    add(n.tcap("Production checklist"))
    yes, no = "✓", "✗"
    add(table(["Пункт", "Стан", "Підтвердження"], [
        ["tests pass", yes, f"{passed.group(1)} тести: Windows (Python 3.12) і Linux (Python "
         f"{python_ci.group(1)}), покриття {coverage.group(1)} %"],
        ["lint passes", yes, "ruff check . і ruff format --check ."],
        ["type checking passes", yes, "mypy --strict (src, tests, tools)"],
        ["wheel builds / sdist builds", yes, f"python -m build, рисунок {build_figure}"],
        ["Docker image builds", no, "не перевірено: на ПК немає Docker"],
        ["container starts", no, "не перевірено; runtime-етап перевірено без Docker (розд. 4)"],
        ["/health returns 200", yes, "у запуску з wheel та командою HEALTHCHECK"],
        ["API works", yes, "запити curl, 52 тести"],
        [".env is ignored / .env.example exists", yes, ".gitignore, .dockerignore, .env.example"],
        ["no secrets in Git", yes, "tools/check_secrets.py: 0 підозрілих рядків"],
        ["README updated", yes, "розділи за рекомендованою структурою"],
        ["CI pipeline green", "частково", "job quality зелений у локальному прогоні; на "
         "GitHub не запускався, job docker не виконувався"],
    ], cls="keep"))

    add("<h1>Висновки</h1>")
    add("<p>Проєкт (варіант 4) доведено до production-oriented версії 1.0.0: пакет з "
        "<code>pyproject.toml</code>, wheel і sdist, які встановлюються в чисте venv; "
        "конфігурація через environment variables з перевіркою під час старту; секрет "
        "<code>API_TOKEN</code> поза кодом, Git і образом, сканер secrets у CI; двоетапний "
        "Dockerfile з non-root користувачем, volume, <code>HEALTHCHECK</code> і "
        "автоматичними міграціями; workflow GitHub Actions з lint, format check, mypy, "
        "тестами з порогом покриття, build і docker build зі smoke test; README зі "
        f"сценарієм демонстрації. Усі {len(quality_ok)} кроків job <code>quality</code> у "
        "локальному прогоні пройшли успішно, а сам прогін допоміг знайти й виправити витік "
        "з'єднань БД. Через відсутність Docker на ПК і публікації на GitHub не виконано "
        "збірку образу, запуск контейнера і «зелений» pipeline на GitHub; runtime-етап "
        "образу натомість перевірено запуском wheel у Linux.</p>")

    body = "\n".join(parts)
    return ("<!doctype html><html lang='uk'><head><meta charset='utf-8'>"
            f"<title>Звіт ЛР10</title><style>{CSS}</style></head><body>{body}</body></html>")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path,
                        default=Path(tempfile.gettempdir()) / "lab10_report_edge_profile")
    args = parser.parse_args()
    html_path = REPORT_DIR / "report.html"
    html_path.write_text(build_html(), encoding="utf-8")
    if PDF_PATH.exists():
        PDF_PATH.unlink()
    edge("--no-pdf-header-footer", "--print-to-pdf-no-header", f"--user-data-dir={args.profile}",
         f"--print-to-pdf={PDF_PATH}", html_path.as_uri())

    try:
        import pymupdf
    except ImportError:
        print(f"PDF: {PDF_PATH}")
        return
    with pymupdf.open(PDF_PATH) as document:
        print(f"PDF: {PDF_PATH} — {document.page_count} сторінок")


if __name__ == "__main__":
    main()
