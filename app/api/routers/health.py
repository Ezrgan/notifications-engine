"""Liveness probe: proves the HTTP process is up without touching product routes."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a fixed ok payload; no I/O, so keep it synchronous."""
    return {"status": "ok"}
