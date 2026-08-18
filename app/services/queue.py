"""Queue port for accepted notifications.

The HTTP path enqueues an id; it never talks to Celery or a provider.
InMemoryNotificationQueue is the v1 adapter until a later phase swaps Celery in.
"""

from __future__ import annotations

import uuid
from typing import Protocol


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
