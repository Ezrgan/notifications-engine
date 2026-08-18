import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import Channel, NotificationStatus
from app.models import Client, Notification

_UNAUTHORIZED = {
    "detail": "Invalid or missing API key",
    "code": "unauthorized",
}

_MINIMAL_BODY = {
    "channel": "email",
    "recipient": "user@example.com",
    "template": "welcome",
}


def _commit_notification(
    engine: Engine,
    client_id: uuid.UUID,
    status: NotificationStatus,
) -> None:
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            Notification(
                client_id=client_id,
                channel=Channel.EMAIL,
                recipient="user@example.com",
                template="welcome",
                payload={},
                status=status,
            )
        )
        session.commit()


def test_metrics_without_api_key_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/metrics")
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED


def test_metrics_empty_history_returns_zeros(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    response = client.get("/api/v1/metrics", headers={"X-API-Key": raw})
    assert response.status_code == 200
    assert response.json() == {"sent": 0, "failed": 0}


def test_metrics_ignores_pending_from_post_send(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    accepted = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    assert accepted.status_code == 202
    response = client.get("/api/v1/metrics", headers={"X-API-Key": raw})
    assert response.status_code == 200
    assert response.json() == {"sent": 0, "failed": 0}


def test_metrics_counts_only_own_sent_and_failed(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    owner_id, raw, _ = seeded_active_client
    _commit_notification(persistence_engine, owner_id, NotificationStatus.SENT)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.SENT)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.FAILED)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.PENDING)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.PROCESSING)

    other_raw = generate_api_key()
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        other = Client(
            name="other-app",
            hashed_api_key=hash_api_key(other_raw),
            is_active=True,
        )
        session.add(other)
        session.commit()
        other_id = other.id
    try:
        _commit_notification(persistence_engine, other_id, NotificationStatus.SENT)
        _commit_notification(persistence_engine, other_id, NotificationStatus.FAILED)

        mine = client.get("/api/v1/metrics", headers={"X-API-Key": raw})
        theirs = client.get("/api/v1/metrics", headers={"X-API-Key": other_raw})
        assert mine.status_code == 200
        assert mine.json() == {"sent": 2, "failed": 1}
        assert theirs.status_code == 200
        assert theirs.json() == {"sent": 1, "failed": 1}
    finally:
        with factory() as session:
            session.execute(delete(Notification).where(Notification.client_id == other_id))
            session.delete(session.get(Client, other_id))
            session.commit()
