"""Accept-send and status probe. The worker process dispatches; this router does not."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_client, get_notification_service
from app.schemas.client import AuthenticatedClient
from app.schemas.notification import (
    NotificationStatusResponse,
    SendAcceptedResponse,
    SendNotificationRequest,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.post(
    "/send",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SendAcceptedResponse,
)
def send_notification(
    body: SendNotificationRequest,
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> SendAcceptedResponse:
    """Persist PENDING and enqueue. Does not call a provider."""
    return service.accept(current_client.id, body)


@router.get(
    "/{notification_id}/status",
    response_model=NotificationStatusResponse,
)
def read_notification_status(
    notification_id: uuid.UUID,
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationStatusResponse:
    """Return status for the owning client. 404 if missing or foreign."""
    return service.get_status(current_client.id, notification_id)
