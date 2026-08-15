"""Data access for Client rows. Routers must not query Session themselves."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client


class ClientRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_hashed_api_key(self, hashed_api_key: str) -> Client | None:
        """Return the client with this digest, or None if no row matches."""
        return self._session.scalar(
            select(Client).where(Client.hashed_api_key == hashed_api_key)
        )
