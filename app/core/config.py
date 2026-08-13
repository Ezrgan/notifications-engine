"""Minimal application settings for local boot (phase 1)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Fail-soft settings: only identity fields; no required secrets yet."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "notifications-engine"
    environment: str = "local"


@lru_cache
def get_settings() -> Settings:
    """Cached settings so every request does not re-read the environment."""
    return Settings()
