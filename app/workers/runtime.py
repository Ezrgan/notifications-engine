"""Worker composition root: one engine per process, one session per task."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_worker_session_factory() -> sessionmaker[Session]:
    """Lazily build the worker engine. FastAPI lifespan must not call this."""
    global _engine, _session_factory
    if _session_factory is None:
        settings = get_settings()
        configure_logging(settings)
        _engine = create_engine_from_url(settings.database_url.get_secret_value())
        _session_factory = create_session_factory(_engine)
    return _session_factory
