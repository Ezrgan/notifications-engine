"""Pydantic v2 schemas for authenticated client responses."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class AuthenticatedClient(BaseModel):
    """What HTTP handlers may see after X-API-Key succeeds. No hash, no secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
