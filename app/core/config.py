"""Application settings loaded from the environment.

`secret_key`, `database_url`, `redis_url`, and `celery_broker_url` are required
so a misconfigured process fails at boot instead of running with silent empty config.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PSYCOPG_URL_PREFIX = "postgresql+psycopg://"
_REDIS_URL_PREFIX = "redis://"


class Settings(BaseSettings):
    """Fail-fast settings: boot dies without secrets and reachable-store URLs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "notifications-engine"
    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secret_key: SecretStr = Field(min_length=16)
    database_url: SecretStr = Field(min_length=1)
    redis_url: SecretStr = Field(min_length=1)
    celery_broker_url: SecretStr = Field(min_length=1)
    rate_limit_per_minute: int = Field(default=10, ge=1)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Accept lowercase env values and normalize to the Literal uppercase set."""
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("database_url")
    @classmethod
    def require_psycopg_url(cls, value: SecretStr) -> SecretStr:
        """Reject SQLite and bare postgresql:// so the driver matches the locked stack."""
        raw = value.get_secret_value()
        if not raw.startswith(_PSYCOPG_URL_PREFIX):
            raise ValueError(
                "DATABASE_URL must start with 'postgresql+psycopg://' "
                "(psycopg v3 driver required)"
            )
        return value

    @field_validator("redis_url")
    @classmethod
    def require_redis_url(cls, value: SecretStr) -> SecretStr:
        """Reject anything that is not a redis:// URL (no Unix socket, no rediss yet)."""
        raw = value.get_secret_value()
        if not raw.startswith(_REDIS_URL_PREFIX):
            raise ValueError("REDIS_URL must start with 'redis://'")
        return value

    @field_validator("celery_broker_url")
    @classmethod
    def require_celery_broker_url(cls, value: SecretStr) -> SecretStr:
        """Broker must be redis:// on a dedicated index, not a hidden default."""
        raw = value.get_secret_value()
        if not raw.startswith(_REDIS_URL_PREFIX):
            raise ValueError("CELERY_BROKER_URL must start with 'redis://'")
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached settings so every request does not re-read the environment."""
    return Settings()  # type: ignore[call-arg]
