"""Unit tests for fail-fast Settings (no app.main import)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_TEST_DATABASE_URL = "postgresql+psycopg://localhost:5432/notifications_engine_test"


def test_missing_secret_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secret_key_shorter_than_16_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_without_psycopg_prefix_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_valid_secret_key_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    settings = Settings(_env_file=None)
    assert "pytest-secret-key" not in repr(settings)
    assert settings.secret_key.get_secret_value() == "pytest-secret-key"
    assert settings.database_url.get_secret_value() == _TEST_DATABASE_URL


def test_invalid_environment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_log_level_is_normalized_to_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("LOG_LEVEL", "info")
    settings = Settings(_env_file=None)
    assert settings.log_level == "INFO"
