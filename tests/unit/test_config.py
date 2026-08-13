"""Unit tests for fail-fast Settings (no app.main import)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_missing_secret_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secret_key_shorter_than_16_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_valid_secret_key_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    settings = Settings(_env_file=None)
    assert "pytest-secret-key" not in repr(settings)
    assert settings.secret_key.get_secret_value() == "pytest-secret-key"


def test_invalid_environment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_log_level_is_normalized_to_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("LOG_LEVEL", "info")
    settings = Settings(_env_file=None)
    assert settings.log_level == "INFO"
