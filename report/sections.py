"""Розділи звіту ЛР10: проєкт, пакет, конфігурація, Docker, API, CI."""

from typing import Any

from html_tools import (
    CAPTURES,
    ROOT,
    SRC,
    Numbering,
    c,
    code,
    extract,
    figure,
    image,
    num,
    para,
    table,
    terminal,
)
from measurements import Package, Quality

TREE = """student-manager/
├── .github/workflows/ci.yml
├── src/student_manager/
│   ├── api.py            REST API, /health, захист записів
│   ├── config.py         Settings (environment variables)
│   ├── database.py       engine, сесії, міграції
│   ├── models.py  repositories.py  services.py  schemas.py
│   ├── caching.py        кеш статистики груп (після Lab_09)
│   ├── main.py           student-manager serve | migrate | config | ...
│   └── migrations/       Alembic (входять у wheel)
├── tests/                unit, integration, production-тести
├── tools/                check_secrets.py, smoke_test.py
├── Dockerfile  .dockerignore  .env.example  .gitignore
├── pyproject.toml  alembic.ini  LICENSE  README.md
"""


def read(name: str) -> str:
    """Текст файлу проєкту."""
    return (ROOT / name).read_text(encoding="utf-8")


def title_page() -> str:
    """Титульна сторінка."""
    return """
<section class="title">
  <div>МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ<br>
  Львівський національний університет імені Івана Франка</div>
  <div class="main">
    <div class="big">ЗВІТ</div>
    <div>до лабораторної роботи №10</div>
    <div>з дисципліни «Професійний Python»</div>
    <div class="theme">Тема: «Production Python: Docker, CI/CD та захист
    проєкту»</div>
  </div>
  <div class="sign">Виконав:<br>студент Левандівський Назар<br><br>
  Перевірив:<br>Куньо Іван Михайлович</div>
  <div class="city">Львів – 2026</div>
</section>"""


def project_section(n: Numbering) -> list[str]:
    """Мета, варіант, опис і структура проєкту."""
    rows = [
        [
            "Продовжити проєкт Lab_01",
            "студент: ім'я, прізвище, група, середній бал",
        ],
        [
            "Предметна функціональність",
            "додавання/перегляд, пошук, фільтр за групою, найкращий студент, "
            "середній бал групи, перенесення між групами",
        ],
        [
            "REST API з Lab_08 + /health",
            "<code>/students</code>, "
            "<code>/groups/{group_id}/students</code>, "
            "<code>/groups/{group_id}/statistics</code>, <code>GET "
            "/health</code>",
        ],
        [
            "Persistence Lab_07 і оптимізації Lab_09",
            "SQLAlchemy + Alembic; кеш статистики груп з інвалідацією",
        ],
        [
            "Environment variables",
            "<code>DATABASE_URL</code>, <code>ENVIRONMENT</code>, "
            "<code>LOG_LEVEL</code> (+ <code>API_TOKEN</code> як секрет)",
        ],
        [
            "Пакет",
            "<code>student-manager</code> / <code>student_manager</code> "
            "1.0.0",
        ],
    ]
    return [
        "<h1>Мета роботи</h1>",
        para(
            "Підготувати проєкт до production-oriented використання: оформити",
            "пакет (wheel і sdist), винести конфігурацію й секрети в "
            "environment",
            "variables, створити Docker image, налаштувати CI/CD у GitHub",
            "Actions і документацію.",
        ),
        "<h1>1. Варіант 1 і структура проєкту</h1>",
        para(
            "<b>Варіант 1. Система обліку студентів.</b> Lab_10 не створює",
            "нову систему, а переводить проєкт Lab_01–Lab_09 у "
            "production-стан.",
            "Вимоги варіанта й реалізація:",
            cls="lead",
        ),
        n.tcap("Вимоги варіанта 1"),
        table(["Вимога", "Реалізація"], rows),
        code(TREE, keep=False),
    ]


def compact(project: str) -> str:
    """Розділ [project] без перелічення classifiers і keywords."""
    lines: list[str] = []
    skipping = False
    for line in project.splitlines():
        if line.startswith(("classifiers", "keywords")):
            skipping = line.startswith("classifiers")
            continue
        if skipping:
            skipping = line.strip() != "]"
            continue
        lines.append(line)
    return "\n".join(lines).rstrip()


def packaging_section(pack: Package) -> list[str]:
    """pyproject.toml, build, dist, метадані й wheel у чистому venv."""
    text = read("pyproject.toml")
    start = text.index("[project]")
    stop = text.index("[project.optional-dependencies]")
    scripts = text[
        text.index("[project.scripts]") : text.index(
            "[tool.setuptools.packages"
        )
    ]
    smoke_lines = pack.smoke.splitlines()
    first = next(
        i
        for i, line in enumerate(smoke_lines)
        if line.startswith("student-manager ")
    )
    shown = [
        line
        for line in smoke_lines[first:]
        if not line.startswith("DATABASE_URL")
    ]
    return [
        "<h1>2. Пакет: pyproject.toml, wheel, sdist</h1>",
        code(compact(text[start:stop]) + "\n\n" + scripts.rstrip()),
        terminal("python -m build", pack.build),
        terminal("Get-ChildItem dist", pack.listing),
        terminal("twine check dist/*", pack.twine),
        para(
            "Метадані зі збудованого wheel і потрібні для роботи файли",
            f"({c('migrations')}, {c('static')}, {c('py.typed')}, "
            f"{c('LICENSE')}):",
            cls="lead",
        ),
        code(pack.metadata, keep=True),
        para("Файли wheel (вибірково):", cls="lead"),
        code(pack.wheel_files, keep=True),
        para(
            f"<b>Перевірка wheel.</b> {c('tools/smoke_test.py --wheel')} "
            f"створює",
            "чисте virtual environment, встановлює wheel (залежності з PyPI),",
            f"запускає {c('student-manager serve')} із production-змінними й",
            "перевіряє API; значення токена в конфігурації приховано:",
        ),
        terminal(
            "python tools/smoke_test.py --wheel dist\\"
            + "student_manager-1.0.0-py3-none-any.whl",
            "\n".join(shown),
        ),
    ]


def configuration_section(quality: Quality) -> list[str]:
    """Конфігурація, .env.example, секрети."""
    return [
        "<h1>3. Конфігурація й секрети</h1>",
        code(
            extract(SRC / "config.py", "Settings", "get_settings"),
            keep=False,
        ),
        terminal(".env.example", read(".env.example")),
        para(
            "<b>Секрети.</b> У коді, README, Dockerfile і Git немає значень",
            f"паролів чи токенів. {c('API_TOKEN')} має тип {c('SecretStr')}",
            "(у repr і журналах – зірочки), береться лише зі змінної "
            "середовища,",
            f"локального {c('.env')} або secrets платформи; у CI одноразовий",
            f"токен створює {c('openssl rand')}, у Docker він передається як",
            f"{c('-e API_TOKEN')} без значення в команді. Пароль у",
            f"{c('DATABASE_URL')} замінюється на *** у журналах. {c('.env')}",
            f"є в {c('.gitignore')} і {c('.dockerignore')}. Аудит:",
        ),
        terminal("python tools/check_secrets.py", quality.secrets),
    ]


def ci_steps(job: dict[str, Any]) -> list[list[str]]:
    """Рядки таблиці кроків job із тривалістю."""
    mark = {"success": "успішно", "skipped": "пропущено"}
    return [
        [
            step["name"],
            mark.get(step["conclusion"], step["conclusion"]),
            f"{step['seconds']} s",
        ]
        for step in job["steps"]
    ]


def docker_section(ci: dict[str, Any], n: Numbering) -> list[str]:
    """Dockerfile, .dockerignore, команди й результат Docker job у CI."""
    docker = next(
        job for job in ci["jobs"] if job["name"].startswith("Docker")
    )
    if docker["conclusion"] != "success":
        raise RuntimeError("Docker job у CI не успішний")
    shot = figure(
        image(CAPTURES / "docker_job.png", 62),
        n.fcap(
            "Сторінка Docker job у GitHub Actions: усі кроки виконано "
            f"(запуск #{ci['number']})"
        ),
    )
    return [
        "<h1>4. Docker</h1>",
        code(read("Dockerfile"), keep=True),
        terminal(".dockerignore", read(".dockerignore")),
        terminal(
            "docker build / docker run (команди з README)",
            "docker build -t student-manager:1.0 .\n"
            "docker run --rm -p 8000:8000 -e ENVIRONMENT=production \\\n"
            "    -e LOG_LEVEL=INFO -v student_data:/app/data "
            "student-manager:1.0\n"
            "docker run -d -p 8000:8000 -e API_TOKEN -v "
            "student_data:/app/data "
            "student-manager:1.0",
        ),
        para(
            "<b>Docker на цьому комп'ютері не встановлено</b>, тому образ",
            f"збирає й запускає CI (runner Ubuntu): крок {c('Build image')}",
            "будує образ за Dockerfile, контейнер стартує з volume, "
            "healthcheck",
            "стає healthy, процес працює від uid 1000, smoke-тест проходить, "
            "а",
            "після перезапуску на тому ж volume дані збережено. Ті самі",
            "production-змінні перевірено локально через wheel (розділ 2).",
        ),
        n.tcap("Кроки Docker job у GitHub Actions"),
        table(["Крок", "Результат", "Час"], ci_steps(docker)),
        shot,
    ]


def api_section(pack: Package, n: Numbering) -> list[str]:
    """REST API, /health і Swagger."""
    health = next(
        line.strip()
        for line in pack.smoke.splitlines()
        if line.strip().startswith('{"status"')
    )
    rows = [
        ["GET /health", "стан сервісу, версія, середовище, база даних"],
        ["GET /students", "пошук за прізвищем, фільтри, сортування, сторінки"],
        [
            "POST /students",
            "додати студента (потрібен X-API-Key за наявності токена)",
        ],
        ["GET /groups/{group_id}/students", "студенти групи"],
        [
            "GET /groups/{group_id}/statistics",
            "кількість, середній, найкращий і найгірший бал",
        ],
        [
            "POST /groups/{group_id}/transfer",
            "перенести студентів між групами",
        ],
    ]
    return [
        "<h1>5. REST API</h1>",
        n.tcap("Основні endpoints"),
        table(["Endpoint", "Призначення"], rows),
        para(
            f"<b>Результат {c('GET /health')}</b> (production-запуск із "
            f"wheel,",
            "HTTP 200; у CI той самий запит виконує smoke-тест у контейнері):",
        ),
        terminal("GET http://127.0.0.1:<port>/health", health),
        figure(
            image(CAPTURES / "swagger.png", 62),
            n.fcap("Swagger UI (/docs) працюючого сервера, версія 1.0.0"),
        ),
    ]


def ci_section(ci: dict[str, Any], n: Numbering) -> list[str]:
    """GitHub Actions workflow та результати pipeline."""
    workflow = read(".github/workflows/ci.yml")
    excerpt = workflow[: workflow.index("      - name: Build wheel and sdist")]
    rows = []
    for job in ci["jobs"]:
        if job["name"].startswith("Docker"):
            continue
        steps = "; ".join(
            f"{step['name']} {step['seconds']} s"
            + (" (пропущено)" if step["conclusion"] == "skipped" else "")
            for step in job["steps"]
        )
        rows.append([job["name"], "успішно", f"{job['seconds']} s", steps])
    shot = figure(
        image(CAPTURES / "run.png", 80),
        n.fcap(
            f"Зелений pipeline: запуск #{ci['number']} для коміту "
            f"{ci['sha'][:7]}"
        ),
    )
    return [
        "<h1>6. CI/CD: GitHub Actions</h1>",
        code(excerpt.rstrip(), keep=False),
        para(
            f"Workflow (продовження): {c('python -m build')}, "
            f"{c('twine check')},",
            "встановлення wheel у чистому середовищі, артефакт dist; job",
            f"{c('docker')} (розділ 4) стартує після успіху {c('quality')}.",
        ),
        n.tcap(
            f"Запуск #{ci['number']} (push у main, {ci['sha'][:7]}): jobs "
            "якості на Python 3.11 і 3.12"
        ),
        table(["Job", "Результат", "Час", "Кроки (тривалість)"], rows),
        shot,
    ]


def quality_section(quality: Quality) -> list[str]:
    """ruff, mypy, pytest."""
    return [
        "<h1>7. Якість: lint, типи, тести</h1>",
        terminal("ruff check .", quality.ruff),
        terminal("ruff format --check .", quality.format),
        terminal("mypy", quality.mypy),
        terminal("pytest -q --cov --cov-report=term-missing", quality.pytest),
    ]


def checklist(
    quality: Quality, pack: Package, ci: dict[str, Any]
) -> list[tuple[str, bool, str]]:
    """Production checklist; кожен пункт перевіряється за даними."""
    docker = next(
        job for job in ci["jobs"] if job["name"].startswith("Docker")
    )
    done = {
        step["name"]: step["conclusion"] == "success"
        for step in docker["steps"]
    }
    ignored = all(
        ".env" in read(name).splitlines()
        for name in (".gitignore", ".dockerignore")
    )
    return [
        (
            "tests pass",
            quality.passed > 0,
            f"{quality.passed} passed, coverage {quality.percent} %",
        ),
        (
            "lint passes",
            "All checks passed" in quality.ruff,
            "ruff check, ruff format --check",
        ),
        (
            "type checking passes",
            quality.mypy.startswith("Success"),
            "mypy --strict",
        ),
        ("wheel builds", "whl" in pack.listing, "dist/*.whl"),
        ("sdist builds", "tar.gz" in pack.listing, "dist/*.tar.gz"),
        (
            "wheel installs in a clean venv",
            "БД збережена: True" in pack.smoke,
            "tools/smoke_test.py --wheel",
        ),
        ("Docker image builds", done["Build image"], "CI: Build image"),
        (
            "container starts and is healthy",
            done["Wait for the Docker healthcheck"],
            "CI: healthcheck",
        ),
        (
            "/health returns 200",
            "GET /health: (200, 'ok')" in pack.smoke
            and done["Smoke test the API"],
            "wheel + CI",
        ),
        (
            "REST API works",
            "OK   POST /students: 201" in pack.smoke,
            "smoke-тест",
        ),
        (
            ".env is ignored",
            ignored and not (ROOT / ".env").exists(),
            ".gitignore, .dockerignore",
        ),
        (
            ".env.example exists",
            (ROOT / ".env.example").exists(),
            ".env.example",
        ),
        (
            "no secrets in Git",
            "підозрілих рядків: 0" in quality.secrets,
            "check_secrets.py",
        ),
        (
            "README updated",
            "## Демонстрація" in read("README.md"),
            "README.md",
        ),
        (
            "CI pipeline green",
            ci["conclusion"] == "success",
            f"запуск #{ci['number']}",
        ),
        (
            "version defined",
            'version = "1.0.0"' in read("pyproject.toml"),
            "1.0.0",
        ),
    ]


def release_section(
    quality: Quality, pack: Package, ci: dict[str, Any], n: Numbering
) -> list[str]:
    """Git commits, production checklist, висновки."""
    log = (CAPTURES / "git_log.txt").read_text(encoding="utf-8").splitlines()
    commits = log[
        next(i for i, line in enumerate(log) if line.startswith("b1421c0"))
        + 1 :
    ]
    rows = []
    for item, passed, evidence in checklist(quality, pack, ci):
        if not passed:
            raise RuntimeError(f"production checklist: {item}")
        rows.append([item, "✓", evidence])
    readme = [
        line
        for line in read("README.md").splitlines()
        if line.startswith("## ")
    ]
    return [
        "<h1>8. Git, README і production checklist</h1>",
        terminal("git log --oneline --reverse", "\n".join(commits)),
        para(
            "<b>README</b> описує систему, встановлення, конфігурацію, "
            "запуск,",
            "Docker, API, тести, CI/CD і сценарій демонстрації; розділи:",
            ", ".join(c(line[3:]) for line in readme) + ".",
        ),
        n.tcap("Production checklist"),
        table(["Пункт", "", "Підтвердження"], rows),
        "<h1>Висновки</h1>",
        para(
            "Проєкт «Система обліку студентів» переведено в "
            "production-oriented",
            "стан: пакет student-manager 1.0.0 (wheel і sdist), конфігурація",
            "через environment variables із секретом типу SecretStr, /health,",
            "багатоетапний Docker image з non-root користувачем, volume для",
            f"SQLite і HEALTHCHECK, CI у GitHub Actions (запуск "
            f"#{ci['number']}",
            "зелений на Python 3.11 і 3.12, Docker job успішний).",
            f"{quality.passed} тестів дають покриття "
            f"{num(float(quality.percent), 2)} %",
            "при порозі 90 %. Обмеження: Docker не встановлено локально, тож",
            "образ збирається й запускається лише в CI.",
        ),
    ]
