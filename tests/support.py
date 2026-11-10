"""Типи й константи для тестів (імпортуються явно, а не з conftest)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

PROJECT_ROOT = Path(__file__).resolve().parents[1]

Query = Callable[..., list[tuple[Any, ...]]]
Serve = Callable[[FastAPI], str]
SetEnv = Callable[..., None]
ENV_NAMES = (
    "APP_NAME",
    "ENVIRONMENT",
    "APP_ENV",
    "DATABASE_URL",
    "LOG_LEVEL",
    "BATCH_CONCURRENCY",
    "BATCH_TIMEOUT",
    "API_TOKEN",
)
