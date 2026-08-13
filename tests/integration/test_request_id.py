"""Integration tests for X-Request-ID middleware."""


def test_health_echoes_generated_request_id(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert request_id.strip() != ""


def test_health_preserves_incoming_request_id(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "client-trace-1"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "client-trace-1"
