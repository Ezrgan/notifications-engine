"""Unit tests for structured logging formatters and configure_logging."""

from __future__ import annotations

import io
import json
import logging

import pytest

from app.core.config import Settings
from app.core.logging import configure_logging

_TEST_DATABASE_URL = "postgresql+psycopg://localhost:5432/notifications_engine_test"


def configure_logging_and_capture(settings: Settings, stream: io.StringIO) -> None:
    """Configure logging then redirect the StreamHandler to ``stream``."""
    configure_logging(settings)
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.stream = stream


def test_production_logging_emits_json_with_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    settings = Settings(_env_file=None)
    stream = io.StringIO()
    configure_logging_and_capture(settings, stream)

    logging.getLogger("app").info("hello", extra={"channel": "email"})
    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["message"] == "hello"
    assert payload["channel"] == "email"
    assert "pytest-secret-key" not in line
    assert "secret_key" not in payload


def test_local_logging_emits_text_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    settings = Settings(_env_file=None)
    stream = io.StringIO()
    configure_logging_and_capture(settings, stream)

    logging.getLogger("app").info("hello")
    line = stream.getvalue().strip().splitlines()[-1]

    assert not line.startswith("{")
    assert "hello" in line
    assert "request_id=-" in line


def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    settings = Settings(_env_file=None)

    configure_logging(settings)
    configure_logging(settings)
    root = logging.getLogger()
    stream_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler)
    ]
    assert len(stream_handlers) == 1
