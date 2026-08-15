import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.models import Client

_UNAUTHORIZED = {
    "detail": "Invalid or missing API key",
    "code": "unauthorized",
}


def test_me_without_header_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/clients/me")
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED
    assert response.headers.get("www-authenticate") == "ApiKey"


def test_health_still_ok_without_api_key(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_me_with_unknown_key_returns_401(client: TestClient) -> None:
    response = client.get(
        "/api/v1/clients/me",
        headers={"X-API-Key": "ne_this-key-is-not-in-the-database"},
    )
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED


def test_me_with_valid_key_returns_client(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    client_id, raw, name = seeded_active_client
    response = client.get("/api/v1/clients/me", headers={"X-API-Key": raw})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(client_id)
    assert body["name"] == name
    assert "hashed_api_key" not in body


def test_me_with_inactive_client_returns_401(
    client: TestClient,
    persistence_engine: Engine,
) -> None:
    raw = generate_api_key()
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        row = Client(
            name="inactive-app",
            hashed_api_key=hash_api_key(raw),
            is_active=False,
        )
        session.add(row)
        session.commit()
        client_id = row.id
    try:
        response = client.get("/api/v1/clients/me", headers={"X-API-Key": raw})
        assert response.status_code == 401
        assert response.json() == _UNAUTHORIZED
    finally:
        with factory() as session:
            session.delete(session.get(Client, client_id))
            session.commit()
