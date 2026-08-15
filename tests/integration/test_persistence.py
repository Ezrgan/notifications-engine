"""Persistence integration tests against real local Postgres (Alembic schema)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models import Client, Notification


def _make_client(*, name: str = "checkout-app", key_suffix: str | None = None) -> Client:
    suffix = key_suffix or uuid.uuid4().hex
    return Client(
        name=name,
        hashed_api_key=f"dummy-hash-not-a-real-key-{suffix}",
        is_active=True,
    )


def test_insert_client_and_notification_defaults(db_session: Session) -> None:
    client = _make_client()
    db_session.add(client)
    db_session.flush()

    notification = Notification(
        client_id=client.id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"x": 1},
    )
    db_session.add(notification)
    db_session.flush()

    db_session.refresh(notification)
    assert notification.status is NotificationStatus.PENDING
    assert notification.payload["x"] == 1
    assert notification.channel is Channel.EMAIL
    assert notification.retry_count == 0
    assert notification.idempotency_key is None


def test_null_idempotency_keys_allowed_twice(db_session: Session) -> None:
    client = _make_client()
    db_session.add(client)
    db_session.flush()

    for _ in range(2):
        db_session.add(
            Notification(
                client_id=client.id,
                channel=Channel.SMS,
                recipient="+15551234567",
                template="otp",
                payload={},
                idempotency_key=None,
            )
        )
    db_session.flush()

    rows = db_session.scalars(
        select(Notification).where(Notification.client_id == client.id)
    ).all()
    assert len(rows) == 2


def test_duplicate_idempotency_key_raises(db_session: Session) -> None:
    client = _make_client()
    db_session.add(client)
    db_session.flush()

    db_session.add(
        Notification(
            client_id=client.id,
            channel=Channel.EMAIL,
            recipient="user@example.com",
            template="welcome",
            payload={},
            idempotency_key="replay-1",
        )
    )
    db_session.flush()

    db_session.add(
        Notification(
            client_id=client.id,
            channel=Channel.EMAIL,
            recipient="other@example.com",
            template="welcome",
            payload={},
            idempotency_key="replay-1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_health_still_ok_without_db_session(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
