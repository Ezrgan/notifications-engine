"""Shared pytest fixtures for the notifications engine test suite."""

from __future__ import annotations

import os
from collections.abc import Generator

# Must run BEFORE importing app.main: create_app() executes at import time and
# Settings() fails without SECRET_KEY / DATABASE_URL / REDIS_URL (fail-fast).
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost:5432/notifications_engine_test",
)
os.environ.setdefault("SECRET_KEY", "pytest-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "10")

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None, None, None]:
    """Clear lru_cache so env monkeypatches are not frozen across tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """HTTP client bound to a fresh app factory instance (no shared singleton)."""
    with TestClient(create_app()) as test_client:
        yield test_client
