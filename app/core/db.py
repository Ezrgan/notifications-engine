"""Sync SQLAlchemy engine and session factory helpers.

The FastAPI lifespan (and persistence tests) own construction. Endpoints must
not call ``create_engine`` themselves.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_url(database_url: str) -> Engine:
    """Build a sync engine. pool_pre_ping survives a local Postgres restart."""
    return create_engine(database_url, pool_pre_ping=True, echo=False)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a factory of short-lived sessions. Callers close or use context managers."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
