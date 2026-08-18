import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import NotificationStatus
from app.main import create_app
from app.models import Client, Notification
from app.services.queue import InMemoryNotificationQueue, QueueUnavailableError

_UNAUTHORIZED = {
    "detail": "Invalid or missing API key",
    "code": "unauthorized",
}
_NOT_FOUND = {
    "detail": "Notification not found",
    "code": "not_found",
}
_UNAVAILABLE = {
    "detail": "Queue unavailable",
    "code": "service_unavailable",
}

_MINIMAL_BODY = {
    "channel": "email",
    "recipient": "user@example.com",
    "template": "welcome",
}


def test_send_without_api_key_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/notifications/send", json=_MINIMAL_BODY)
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED


def test_send_invalid_channel_returns_422(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    response = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json={**_MINIMAL_BODY, "channel": "fax"},
    )
    assert response.status_code == 422


def test_send_returns_202_pending_and_enqueues_once(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    client_id, raw, _ = seeded_active_client
    response = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    assert response.status_code == 202
    body = response.json()
    notification_id = uuid.UUID(body["notification_id"])
    assert body["status"] == "PENDING"

    queue = client.app.state.notification_queue
    assert isinstance(queue, InMemoryNotificationQueue)
    assert queue.enqueued == [notification_id]

    factory = create_session_factory(persistence_engine)
    with factory() as session:
        row = session.get(Notification, notification_id)
        assert row is not None
        assert row.client_id == client_id
        assert row.status is NotificationStatus.PENDING


def test_send_replay_same_idempotency_key_does_not_double_enqueue(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    payload = {**_MINIMAL_BODY, "idempotency_key": "checkout-99"}
    headers = {"X-API-Key": raw}
    first = client.post("/api/v1/notifications/send", headers=headers, json=payload)
    second = client.post("/api/v1/notifications/send", headers=headers, json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["notification_id"] == second.json()["notification_id"]
    queue = client.app.state.notification_queue
    assert queue.enqueued == [uuid.UUID(first.json()["notification_id"])]


def test_status_own_notification_returns_pending(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    created = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    notification_id = created.json()["notification_id"]
    response = client.get(
        f"/api/v1/notifications/{notification_id}/status",
        headers={"X-API-Key": raw},
    )
    assert response.status_code == 200
    assert response.json() == {
        "notification_id": notification_id,
        "status": "PENDING",
    }


def test_status_foreign_or_missing_returns_same_404(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    _, raw, _ = seeded_active_client
    created = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    notification_id = created.json()["notification_id"]

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
        foreign = client.get(
            f"/api/v1/notifications/{notification_id}/status",
            headers={"X-API-Key": other_raw},
        )
        missing = client.get(
            f"/api/v1/notifications/{uuid.uuid4()}/status",
            headers={"X-API-Key": raw},
        )
        assert foreign.status_code == 404
        assert missing.status_code == 404
        assert foreign.json() == _NOT_FOUND
        assert missing.json() == _NOT_FOUND
    finally:
        with factory() as session:
            session.execute(delete(Notification).where(Notification.client_id == other_id))
            session.delete(session.get(Client, other_id))
            session.commit()


def test_send_returns_503_when_queue_raises(
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    client_id, raw, _ = seeded_active_client

    class BoomQueue:
        def enqueue(self, notification_id: uuid.UUID) -> None:
            raise QueueUnavailableError()

    with TestClient(create_app()) as test_client:
        test_client.app.state.notification_queue = BoomQueue()
        response = test_client.post(
            "/api/v1/notifications/send",
            headers={"X-API-Key": raw},
            json=_MINIMAL_BODY,
        )
        assert response.status_code == 503
        assert response.json() == _UNAVAILABLE
        factory = create_session_factory(persistence_engine)
        with factory() as session:
            rows = session.scalars(
                select(Notification).where(Notification.client_id == client_id)
            ).all()
            assert len(rows) == 1
            assert rows[0].status is NotificationStatus.PENDING
