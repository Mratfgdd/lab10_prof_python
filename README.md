# Student Manager

REST API системи обліку студентів (варіант 1) у production-oriented вигляді:
пакет `student-manager`, конфігурація через environment variables, Docker,
CI/CD (GitHub Actions) і документація. Продовження проєкту Lab_01: студент має
ім'я, прізвище, групу й середній бал; поверх шару збереження (SQLAlchemy +
Alembic, Lab_07) працює REST API (FastAPI, Lab_08), а повторна статистика груп
кешується (оптимізація за результатами Lab_09).

## Можливості

- додавання, перегляд, зміна й видалення студентів;
- пошук за прізвищем, фільтри за групою й балом, сортування, сторінки;
- найкращий студент, середній бал і статистика групи;
- перенесення студентів між групами однією транзакцією;
- `GET /health` для Docker і оркестраторів;
- необов'язковий захист записів заголовком `X-API-Key`;
- SQLite, міграції Alembic, кеш статистики груп з інвалідацією;
- wheel і sdist, Docker image, CI.

## Структура

```
src/student_manager/
    api.py            REST API: endpoints, помилки, create_app(), /health
    config.py         Settings (pydantic-settings): environment variables
    database.py       engine, сесії, міграції
    models.py         ORM-моделі Group і Student
    repositories.py   шар репозиторіїв
    services.py       бізнес-логіка й транзакції
    caching.py        кеш статистики груп
    main.py           команди student-manager (serve, migrate, config, ...)
    migrations/       міграції Alembic (входять у wheel)
tests/                unit, integration і production-тести
tools/                check_secrets.py, smoke_test.py, call_api.py
Dockerfile  .dockerignore  .env.example  alembic.ini
.github/workflows/ci.yml
```

## Встановлення

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Лише для запуску (без інструментів розробки): `pip install .`

## Конфігурація

Усі параметри задаються змінними середовища; для локальної роботи їх можна
покласти у файл `.env` (його немає в Git і в Docker image):

```
cp .env.example .env
```

| Змінна | Призначення | Типово |
| --- | --- | --- |
| `ENVIRONMENT` (або `APP_ENV`) | `development`, `test`, `production` | `development` |
| `DATABASE_URL` | URL бази даних | `sqlite:///students.db` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `APP_NAME` | назва в OpenAPI | `Student Manager API` |
| `BATCH_CONCURRENCY`, `BATCH_TIMEOUT` | пакетна статистика груп | `5`, `10` |
| `API_TOKEN` | секрет: якщо задано, зміни даних потребують `X-API-Key` | не задано |

Реальні значення секретів не зберігаються в коді, README, Dockerfile чи Git:
`API_TOKEN` і пароль у `DATABASE_URL` надходять лише зі змінних середовища,
локального `.env` або secrets платформи (GitHub Actions secrets,
`docker run --env-file`). Поточну конфігурацію без значень секретів показує
`student-manager config`.

Приклад зміни без правки коду:

```
export LOG_LEVEL=DEBUG
$env:LOG_LEVEL = "DEBUG"
```

## Запуск

```
student-manager migrate
student-manager serve
```

`serve` спершу застосовує міграції (`--no-migrate` вимикає), потім запускає
uvicorn. Документація: <http://127.0.0.1:8000/docs>, схема: `/openapi.json`.

Консольні команди роботи з БД: `seed`, `groups`, `students`, `find`, `add`,
`grade`, `transfer`, `best`, `average`, `delete` (`student-manager --help`).

## Docker

```
docker build -t student-manager:1.0 .
docker run --rm -p 8000:8000 -e ENVIRONMENT=production -e LOG_LEVEL=INFO \
    -v student_data:/app/data student-manager:1.0
```

Образ багатоетапний: wheel збирається в окремому етапі, фінальний образ містить
лише Python і встановлений пакет, процес працює від користувача `appuser`.
База SQLite лежить у `/app/data` (volume), тому дані переживають перезапуск.
`HEALTHCHECK` опитує `/health`. Секрет передається без значення в команді:

```
docker run -d -p 8000:8000 -e API_TOKEN -v student_data:/app/data student-manager:1.0
```

## API

| Метод і шлях | Призначення |
| --- | --- |
| `GET /health` | стан сервісу, версія, середовище, база даних |
| `GET /students` | список: `last_name`, `group_id`, `min_grade`, `max_grade`, `sort`, `order`, `limit`, `offset` |
| `GET /students/best` | найкращий студент |
| `GET /students/{student_id}` | студент за id |
| `POST /students` | додати студента |
| `PATCH /students/{student_id}` | змінити бал, групу, ім'я, email |
| `DELETE /students/{student_id}` | видалити студента |
| `GET /groups` | групи зі статистикою |
| `POST /groups` | створити групу |
| `GET /groups/{group_id}/students` | студенти групи |
| `GET /groups/{group_id}/statistics` | кількість, середній, найкращий і найгірший бал |
| `POST /groups/{group_id}/transfer` | перенести студентів до групи |
| `POST /statistics/groups` | статистика кількох груп паралельно |

Помилки мають вигляд `{"error": "...", "detail": "..."}` (401, 404, 409, 422).
`POST`, `PATCH` і `DELETE` потребують заголовок `X-API-Key`, якщо задано
`API_TOKEN`; читання й `/health` відкриті.

## Тести

```
pytest -v --cov --cov-report=term-missing
ruff check .
ruff format --check .
mypy
python tools/check_secrets.py
```

Поріг покриття – 90 % (`pyproject.toml`).

## Пакет

```
python -m build
twine check dist/*
python tools/smoke_test.py --wheel dist/student_manager-1.0.0-py3-none-any.whl
```

Створюються `dist/student_manager-1.0.0-py3-none-any.whl` і
`dist/student_manager-1.0.0.tar.gz`. `smoke_test.py` встановлює wheel у чисте
virtual environment, виконує міграції, запускає сервер і перевіряє API.

## CI/CD

`.github/workflows/ci.yml` виконується на кожен push у `main` і pull request:

1. **quality** (Python 3.11 і 3.12): сканування секретів, `ruff check`,
   `ruff format --check`, `mypy`, `pytest` із покриттям, `python -m build`,
   `twine check`, встановлення wheel у чисте середовище, артефакт `dist`;
2. **docker**: `docker build`, запуск контейнера з volume, очікування
   Docker healthcheck, перевірка non-root користувача, smoke-тест API,
   перезапуск на тому ж volume й перевірка збереження даних.

Одноразовий токен для CI створюється `openssl rand` у самому workflow.

## Демонстрація

1. `pytest -v`, `ruff check .`, `mypy` – якість коду.
2. `python -m build` – wheel і sdist у `dist/`.
3. `docker build -t student-manager:1.0 .` і `docker run ...` (див. вище).
4. `GET /health` → `{"status": "ok", "environment": "production", ...}`.
5. `/docs`: створити групу `PI-21` (`POST /groups`), студента (`POST /students`),
   отримати `GET /groups/1/statistics`; перенести студента `POST /groups/2/transfer`.
6. Перезапустити контейнер на тому ж volume – дані на місці.
7. Показати зелений pipeline у GitHub Actions, `.env.example` і `.gitignore`.

## Ліцензія

MIT, див. `LICENSE`.
