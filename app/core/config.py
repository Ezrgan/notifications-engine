"""Application settings loaded from the environment.

`secret_key` is required so a misconfigured process fails at boot instead of
running with silent empty config. `DATABASE_URL` and `REDIS_URL` are intentionally
absent: nothing in this phase opens Postgres or Redis, so requiring them would
force fake connection strings we do not use yet.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Fail-fast settings: boot dies without a usable SECRET_KEY."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "notifications-engine"
    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secret_key: SecretStr = Field(min_length=16)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Accept lowercase env values and normalize to the Literal uppercase set."""
        if isinstance(value, str):
            return value.upper()
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached settings so every request does not re-read the environment."""
    return Settings()
