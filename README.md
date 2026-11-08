# Bank Account Service

## Description

REST API системи банківських рахунків: клієнти, рахунки, поповнення, списання, атомарні
перекази й історія операцій. Варіант 4 курсу «Професійний Python» (ЛР1–ЛР10):
production-версія проєкту - пакет, конфігурація через environment, Docker і CI/CD.

## Features

- Клієнти та рахунки (UA-NNNN), поповнення і списання; від'ємний баланс заборонений.
- Атомарний переказ (транзакція SQLAlchemy, optimistic locking, повтор при конфлікті).
- Історія операцій, пошук і фільтри рахунків, загальна сума коштів за валютами.
- Прогноз відсотків (10 % річних, щоденна капіталізація) на NumPy - оптимізація з ЛР9.
- SQLite + SQLAlchemy 2 + Alembic; міграції застосовуються під час запуску сервісу.
- FastAPI + Pydantic, Swagger UI (`/docs`) без CDN, `GET /health` для Docker HEALTHCHECK.
- Асинхронний клієнт `bank-api-client` (httpx: Task, gather, TaskGroup, Semaphore, timeout, retry).

## Requirements

Python 3.11+ або Docker.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # для розробки
pip install dist/bank_account_service-1.0.0-py3-none-any.whl   # або встановити wheel
```

## Configuration

Усі параметри - environment variables (або файл `.env` для локальної розробки):

```bash
cp .env.example .env
```

| Змінна | Типово | Опис |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` або `production` |
| `DATABASE_URL` | `sqlite:///bank.db` | URL бази SQLAlchemy |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CONFLICT_RETRIES` | `3` | повтори операції при конфлікті версій (0–10) |
| `API_TOKEN` | не задано | **секрет**: якщо задано, POST/PATCH/DELETE вимагають `X-API-Key` |

Секрети не зберігаються в коді, README, Dockerfile чи Git. `.env` є в `.gitignore` і
`.dockerignore`, значення передаються через середовище, `docker run --env-file` або
GitHub Actions secrets. `bank-account-service config` показує конфігурацію з прихованими
секретами, `python tools/check_secrets.py` перевіряє проєкт на секрети (крок CI).

## Running locally

```bash
bank-account-service serve          # міграції + uvicorn на http://127.0.0.1:8000
bank-account-service migrate        # лише міграції (alembic upgrade head)
bank-account-service config         # ефективна конфігурація
```

## Running with Docker

```bash
docker build -t bank-account-service:1.0.0 .
docker run -d --name bank -p 8000:8000 \
    -v bank_data:/app/data \
    -e APP_ENV=production -e LOG_LEVEL=INFO \
    --env-file .env \
    bank-account-service:1.0.0
curl http://localhost:8000/health
```

Образ двоетапний (wheel збирається в окремому етапі), працює від користувача `appuser`,
має `HEALTHCHECK`; SQLite-файл зберігається у volume `/app/data`.

## API

Документація: `/docs` (Swagger UI), `/openapi.json` (схема OpenAPI).

| Метод | URL | Опис |
|---|---|---|
| GET | `/health` | стан сервісу і БД |
| POST | `/clients` | створити клієнта |
| GET | `/clients/{id}` | клієнт |
| POST | `/accounts` | відкрити рахунок |
| GET | `/accounts` | пошук і фільтри (number, client_id, currency, account_type, min_balance, sort, order, limit, offset) |
| GET / PATCH / DELETE | `/accounts/{id}` | рахунок і баланс / змінити тип / закрити |
| GET | `/accounts/{id}/transactions` | історія операцій |
| POST | `/accounts/{id}/deposit`, `/accounts/{id}/withdraw` | поповнення, списання |
| POST | `/transfers` | атомарний переказ |
| GET | `/statistics/funds`, `/statistics/interest` | загальна сума коштів, прогноз відсотків |

```bash
curl -X POST localhost:8000/clients -H "Content-Type: application/json" \
     -H "X-API-Key: $API_TOKEN" -d '{"full_name": "Олена Коваленко"}'
```

## Testing

```bash
pytest -v --cov            # 52 тести, поріг покриття 85 %
ruff check . && ruff format --check . && mypy
python -m build            # dist/*.whl і dist/*.tar.gz
```

## Project structure

```
src/bank_account_service/   api, config, database, models, repositories, services,
                            schemas, interest, external_api, main; migrations/; static/
tests/                      API, клієнт, конфігурація, health, secrets, CLI
tools/                      check_secrets.py, call_api.py
.github/workflows/ci.yml    CI: secret scan, ruff, mypy, pytest, build, docker
Dockerfile, .dockerignore, .env.example, pyproject.toml, alembic.ini, LICENSE
```

## CI/CD

`.github/workflows/ci.yml` на кожен push у `main` і pull request: job `quality`
(Python 3.11 і 3.12) - secret scan, ruff check, ruff format --check, mypy, pytest з
покриттям, build wheel/sdist, встановлення wheel у чисте venv, artifact `dist`; job `docker`
- збірка образу та smoke test `/health` у запущеному контейнері.

## Demo scenario

1. `pytest -v`, `ruff check .`, `mypy` - якість коду.
2. `python -m build` - `dist/` з wheel і sdist.
3. `docker build -t bank-account-service:1.0.0 .`, `docker images`.
4. `docker run ...` (див. вище), `docker ps` - контейнер `healthy`.
5. `curl localhost:8000/health`, `/docs`; створити клієнта, рахунки, переказ, історію.
6. Показати `.env.example`, `bank-account-service config` і CI workflow.

## Authors

Nazar Levandivskyi
