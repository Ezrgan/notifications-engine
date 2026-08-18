"""Use cases: accept a send request and read status for the owning client."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import NotificationNotFound
from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import (
    NotificationStatusResponse,
    SendAcceptedResponse,
    SendNotificationRequest,
)
from app.services.queue import NotificationQueue, QueueUnavailableError

logger = logging.getLogger("app.notifications")


class NotificationService:
    def __init__(
        self,
        session: Session,
        repository: NotificationRepository,
        queue: NotificationQueue,
    ) -> None:
        self._session = session
        self._repository = repository
        self._queue = queue

    def accept(
        self,
        client_id: uuid.UUID,
        request: SendNotificationRequest,
    ) -> SendAcceptedResponse:
        """Persist PENDING, commit, enqueue id. Idempotent replays skip enqueue."""
        if request.idempotency_key is not None:
            existing = self._repository.get_by_idempotency_key(
                client_id, request.idempotency_key
            )
            if existing is not None:
                logger.info(
                    "notification_idempotent_replay",
                    extra={
                        "notification_id": str(existing.id),
                        "client_id": str(client_id),
                        "channel": existing.channel.value,
                        "status": existing.status.value,
                    },
                )
                return self._to_accepted(existing)

        row = self._repository.create(
            client_id=client_id,
            channel=request.channel,
            recipient=request.recipient,
            template=request.template,
            payload=request.payload,
            idempotency_key=request.idempotency_key,
        )
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if request.idempotency_key is None:
                raise
            winner = self._repository.get_by_idempotency_key(
                client_id, request.idempotency_key
            )
            if winner is None:
                raise
            return self._to_accepted(winner)

        try:
            self._queue.enqueue(row.id)
        except QueueUnavailableError:
            raise
        except Exception as exc:
            raise QueueUnavailableError() from exc

        logger.info(
            "notification_accepted",
            extra={
                "notification_id": str(row.id),
                "client_id": str(client_id),
                "channel": row.channel.value,
                "status": row.status.value,
            },
        )
        return self._to_accepted(row)

    def get_status(
        self,
        client_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> NotificationStatusResponse:
        """Return status for the owning client or raise NotificationNotFound."""
        row = self._repository.get_by_id_for_client(notification_id, client_id)
        if row is None:
            raise NotificationNotFound()
        logger.info(
            "notification_status_read",
            extra={
                "notification_id": str(row.id),
                "client_id": str(client_id),
                "channel": row.channel.value,
                "status": row.status.value,
            },
        )
        return NotificationStatusResponse(
            notification_id=row.id,
            status=row.status,
        )

    @staticmethod
    def _to_accepted(row: Notification) -> SendAcceptedResponse:
        return SendAcceptedResponse(notification_id=row.id, status=row.status)
