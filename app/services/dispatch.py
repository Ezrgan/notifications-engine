"""Use case: dispatch one persisted notification through a provider port."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domain.enums import NotificationStatus
from app.domain.state_machine import assert_transition
from app.providers.port import NotificationProvider, OutboundMessage, ProviderError
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger("app.dispatch")

_ERROR_MESSAGE_MAX = 512


class DispatchService:
    def __init__(
        self,
        session: Session,
        repository: NotificationRepository,
        provider: NotificationProvider,
    ) -> None:
        self._session = session
        self._repository = repository
        self._provider = provider

    def dispatch(self, notification_id: uuid.UUID) -> None:
        """Load, skip terminals, PROCESSING → provider → SENT or FAILED. Commits here."""
        row = self._repository.get_by_id(notification_id)
        if row is None:
            logger.warning(
                "notification_dispatch_missing",
                extra={"notification_id": str(notification_id)},
            )
            return

        if row.status in {NotificationStatus.SENT, NotificationStatus.FAILED}:
            logger.info(
                "notification_dispatch_skipped",
                extra={
                    "notification_id": str(row.id),
                    "client_id": str(row.client_id),
                    "channel": row.channel.value,
                    "status": row.status.value,
                    "retry_count": row.retry_count,
                },
            )
            return

        if row.status is NotificationStatus.PENDING:
            assert_transition(row.status, NotificationStatus.PROCESSING)
            row.status = NotificationStatus.PROCESSING
            self._session.commit()

        logger.info(
            "notification_dispatch_started",
            extra={
                "notification_id": str(row.id),
                "client_id": str(row.client_id),
                "channel": row.channel.value,
                "status": row.status.value,
                "retry_count": row.retry_count,
            },
        )

        message = OutboundMessage(
            channel=row.channel,
            recipient=row.recipient,
            template=row.template,
            payload=row.payload,
        )
        try:
            self._provider.send(message)
        except Exception as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc))
            assert_transition(row.status, NotificationStatus.FAILED)
            row.status = NotificationStatus.FAILED
            row.error_message = str(error)[:_ERROR_MESSAGE_MAX]
            self._session.commit()
            logger.info(
                "notification_dispatch_failed",
                extra={
                    "notification_id": str(row.id),
                    "client_id": str(row.client_id),
                    "channel": row.channel.value,
                    "status": row.status.value,
                    "retry_count": row.retry_count,
                },
                exc_info=True,
            )
            return

        assert_transition(row.status, NotificationStatus.SENT)
        row.status = NotificationStatus.SENT
        row.sent_at = datetime.now(UTC)
        row.error_message = None
        self._session.commit()
        logger.info(
            "notification_sent",
            extra={
                "notification_id": str(row.id),
                "client_id": str(row.client_id),
                "channel": row.channel.value,
                "status": row.status.value,
                "retry_count": row.retry_count,
            },
        )
