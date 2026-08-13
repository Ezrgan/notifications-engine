"""Shared pytest fixtures for the notifications engine test suite."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """HTTP client bound to a fresh app factory instance (no shared singleton)."""
    with TestClient(create_app()) as test_client:
        yield test_client
