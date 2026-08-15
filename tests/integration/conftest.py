"""Integration fixtures: real Postgres + Alembic upgrade (no create_all)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from alembic import command
from app.core.db import create_engine_from_url, create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.models import Client, Notification

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def persistence_engine() -> Generator[Engine, None, None]:
    """Apply Alembic migrations once per session against the test database."""
    database_url = os.environ["DATABASE_URL"]
    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_cfg, "head")

    engine = create_engine_from_url(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(persistence_engine: Engine) -> Generator[Session, None, None]:
    """Per-test session wrapped in a transaction that always rolls back."""
    connection = persistence_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        # IntegrityError aborts the transaction; only roll back if still open.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def seeded_active_client(
    persistence_engine: Engine,
) -> Generator[tuple[uuid.UUID, str, str], None, None]:
    """Commit one active client so TestClient (separate pool) can authenticate."""
    raw = generate_api_key()
    name = f"auth-test-{uuid.uuid4().hex[:8]}"
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        row = Client(name=name, hashed_api_key=hash_api_key(raw), is_active=True)
        session.add(row)
        session.commit()
        session.refresh(row)
        client_id = row.id
    yield client_id, raw, name
    with factory() as session:
        session.execute(delete(Notification).where(Notification.client_id == client_id))
        session.execute(delete(Client).where(Client.id == client_id))
        session.commit()
