"""Queue port for accepted notifications.

The HTTP path enqueues an id; it never talks to a provider.
InMemoryNotificationQueue is the test adapter. CeleryNotificationQueue is local/prod.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Protocol


class QueueUnavailableError(Exception):
    """Raised when enqueue cannot complete. HTTP handler maps this to 503."""


class NotificationQueue(Protocol):
    """Application-owned port: accept a notification id for later dispatch."""

    def enqueue(self, notification_id: uuid.UUID) -> None:
        """Record ``notification_id``. Must not send the notification.

        Adapters may raise ``QueueUnavailableError``.
        """
        ...


class InMemoryNotificationQueue:
    """Process-local list. Lost on restart; Postgres still holds PENDING rows."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    def enqueue(self, notification_id: uuid.UUID) -> None:
        self.enqueued.append(notification_id)


class CeleryNotificationQueue:
    """Publish notification ids to the Celery ``notifications`` queue."""

    def __init__(self, apply_async: Callable[..., Any] | None = None) -> None:
        self._apply_async = apply_async

    def enqueue(self, notification_id: uuid.UUID) -> None:
        publish = self._apply_async
        if publish is None:
            from app.workers.tasks import deliver_notification

            publish = deliver_notification.apply_async
        try:
            publish(args=[str(notification_id)], queue="notifications")
        except QueueUnavailableError:
            raise
        except Exception as exc:
            raise QueueUnavailableError() from exc
