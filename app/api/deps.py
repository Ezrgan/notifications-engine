"""FastAPI dependencies: DB session and current client from X-API-Key."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.api.errors import UnauthorizedError
from app.core.security import hash_api_key
from app.repositories.client_repository import ClientRepository
from app.repositories.notification_repository import NotificationRepository
from app.schemas.client import AuthenticatedClient
from app.services.notification_service import NotificationService
from app.services.queue import NotificationQueue

logger = logging.getLogger("app.auth")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a short-lived session from the lifespan factory. Do not commit here."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_client(
    session: Annotated[Session, Depends(get_db)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> AuthenticatedClient:
    """Resolve X-API-Key to an active client. Never return the ORM model to routers."""
    if not api_key:
        logger.info("api_key_rejected", extra={"reason": "missing"})
        raise UnauthorizedError()

    client = ClientRepository(session).get_by_hashed_api_key(hash_api_key(api_key))
    if client is None or not client.is_active:
        logger.info("api_key_rejected", extra={"reason": "unknown_or_inactive"})
        raise UnauthorizedError()

    logger.info("client_authenticated", extra={"client_id": str(client.id)})
    return AuthenticatedClient(id=client.id, name=client.name)


def get_notification_queue(request: Request) -> NotificationQueue:
    """Return the queue adapter owned by lifespan (app.state)."""
    queue: NotificationQueue = request.app.state.notification_queue
    return queue


def get_notification_service(
    session: Annotated[Session, Depends(get_db)],
    queue: Annotated[NotificationQueue, Depends(get_notification_queue)],
) -> NotificationService:
    """Compose the send/status use case for one request."""
    return NotificationService(
        session=session,
        repository=NotificationRepository(session),
        queue=queue,
    )
