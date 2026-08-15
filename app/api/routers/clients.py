"""Authenticated client probe. Product send routes arrive in a later phase."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_client
from app.schemas.client import AuthenticatedClient

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


@router.get("/me", response_model=AuthenticatedClient)
def read_me(
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
) -> AuthenticatedClient:
    """Return the active client bound to X-API-Key. 401 is handled in deps."""
    return current_client
