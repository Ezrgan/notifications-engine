import uuid

from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import Engine, delete, func, select

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.main import create_app
from app.models import Client, Notification

_MINIMAL_BODY = {
    "channel": "email",
    "recipient": "user@example.com",
    "template": "welcome",
}
_RATE_LIMITED = {
    "detail": "Rate limit exceeded",
    "code": "rate_limited",
}
_LIMITER_UNAVAILABLE = {
    "detail": "Rate limiter unavailable",
    "code": "service_unavailable",
}


def test_eleventh_send_returns_429(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    headers = {"X-API-Key": raw}
    responses = [
        client.post("/api/v1/notifications/send", headers=headers, json=_MINIMAL_BODY)
        for _ in range(11)
    ]
    assert [r.status_code for r in responses[:10]] == [202] * 10
    last = responses[10]
    assert last.status_code == 429
    assert last.json() == _RATE_LIMITED
    assert int(last.headers["retry-after"]) >= 1


def test_429_does_not_insert_an_eleventh_row(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    client_id, raw, _ = seeded_active_client
    headers = {"X-API-Key": raw}
    for _ in range(11):
        client.post("/api/v1/notifications/send", headers=headers, json=_MINIMAL_BODY)
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        count = session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.client_id == client_id
            )
        )
    assert count == 10


def test_second_api_key_is_not_blocked_by_first_bucket(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    _, raw_a, _ = seeded_active_client
    headers_a = {"X-API-Key": raw_a}
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/notifications/send", headers=headers_a, json=_MINIMAL_BODY
            ).status_code
            == 202
        )

    raw_b = generate_api_key()
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        other = Client(
            name="other-limited-app",
            hashed_api_key=hash_api_key(raw_b),
            is_active=True,
        )
        session.add(other)
        session.commit()
        other_id = other.id
    try:
        ok = client.post(
            "/api/v1/notifications/send",
            headers={"X-API-Key": raw_b},
            json=_MINIMAL_BODY,
        )
        assert ok.status_code == 202
    finally:
        with factory() as session:
            session.execute(delete(Notification).where(Notification.client_id == other_id))
            session.delete(session.get(Client, other_id))
            session.commit()


def test_unauthenticated_probe_is_429_after_ip_bucket_exhausts(client: TestClient) -> None:
    responses = [
        client.post("/api/v1/notifications/send", json=_MINIMAL_BODY) for _ in range(11)
    ]
    assert responses[0].status_code == 401
    assert responses[10].status_code == 429
    assert responses[10].json() == _RATE_LIMITED


def test_health_and_metrics_are_not_rate_limited(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    headers = {"X-API-Key": raw}
    for _ in range(10):
        client.post("/api/v1/notifications/send", headers=headers, json=_MINIMAL_BODY)
    assert client.get("/health").status_code == 200
    metrics = client.get("/api/v1/metrics", headers=headers)
    assert metrics.status_code == 200
    assert metrics.json() == {"sent": 0, "failed": 0}


def test_send_returns_503_when_redis_raises(
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    class BoomBucket:
        def consume(self, *args: object, **kwargs: object) -> None:
            raise RedisError("down")

    _, raw, _ = seeded_active_client
    with TestClient(create_app()) as test_client:
        test_client.app.state.token_bucket = BoomBucket()
        response = test_client.post(
            "/api/v1/notifications/send",
            headers={"X-API-Key": raw},
            json=_MINIMAL_BODY,
        )
        assert response.status_code == 503
        assert response.json() == _LIMITER_UNAVAILABLE
        factory = create_session_factory(persistence_engine)
        with factory() as session:
            count = session.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.client_id == seeded_active_client[0]
                )
            )
        assert count == 0
