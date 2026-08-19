"""Use case: dispatch one persisted notification through a provider port."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.domain.enums import NotificationStatus
from app.domain.retry_policy import DeliveryRetryPolicy
from app.domain.state_machine import assert_transition
from app.models.notification import Notification
from app.providers.port import (
    NotificationProvider,
    OutboundMessage,
    PermanentProviderError,
)
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger("app.dispatch")

_ERROR_MESSAGE_MAX = 512


class DispatchAction(StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"
    MISSING = "missing"
    RETRY = "retry"
    FAILED = "failed"


@dataclass(frozen=True)
class DispatchResult:
    """What the worker task should do after this attempt. No Celery types here."""

    action: DispatchAction
    countdown_seconds: int | None = None
    dead_letter: bool = False


class DispatchService:
    def __init__(
        self,
        session: Session,
        repository: NotificationRepository,
        provider: NotificationProvider,
        policy: DeliveryRetryPolicy,
    ) -> None:
        self._session = session
        self._repository = repository
        self._provider = provider
        self._policy = policy

    def dispatch(self, notification_id: uuid.UUID) -> DispatchResult:
        """Load, skip terminals, PROCESSING → provider → SENT, RETRY, or FAILED. Commits here."""
        row = self._repository.get_by_id(notification_id)
        if row is None:
            logger.warning(
                "notification_dispatch_missing",
                extra={"notification_id": str(notification_id)},
            )
            return DispatchResult(DispatchAction.MISSING)

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
            return DispatchResult(DispatchAction.SKIPPED)

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
            return self._handle_send_failure(row, exc)

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
        return DispatchResult(DispatchAction.SENT)

    def _handle_send_failure(self, row: Notification, exc: Exception) -> DispatchResult:
        retryable = not isinstance(exc, PermanentProviderError)
        row.retry_count += 1
        row.error_message = str(exc)[:_ERROR_MESSAGE_MAX]
        extras = {
            "notification_id": str(row.id),
            "client_id": str(row.client_id),
            "channel": row.channel.value,
            "status": row.status.value,
            "retry_count": row.retry_count,
        }

        if self._policy.should_retry(row.retry_count, retryable=retryable):
            countdown = self._policy.countdown_for(row.retry_count)
            assert_transition(row.status, NotificationStatus.PENDING)
            row.status = NotificationStatus.PENDING
            self._session.commit()
            logger.info("notification_retry_scheduled", extra=extras)
            return DispatchResult(
                DispatchAction.RETRY,
                countdown_seconds=countdown,
            )

        assert_transition(row.status, NotificationStatus.FAILED)
        row.status = NotificationStatus.FAILED
        self._session.commit()
        logger.info("notification_dispatch_failed", extra=extras, exc_info=True)
        return DispatchResult(DispatchAction.FAILED, dead_letter=True)
