"""Data access for Notification rows. Routers must not query Session themselves."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models.notification import Notification


@dataclass(frozen=True)
class ClientSendCounts:
    """Terminal send counts for one client. PENDING/PROCESSING are not included."""

    sent: int
    failed: int


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        client_id: uuid.UUID,
        channel: Channel,
        recipient: str,
        template: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> Notification:
        """Add a PENDING row with a client-side UUID. Caller commits."""
        row = Notification(
            id=uuid.uuid4(),
            client_id=client_id,
            channel=channel,
            recipient=recipient,
            template=template,
            payload=payload,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        return row

    def get_by_id_for_client(
        self,
        notification_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> Notification | None:
        """Return the row only if it belongs to ``client_id``."""
        return self._session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.client_id == client_id,
            )
        )

    def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        """Load by primary key. Worker path only; not an HTTP authorization check."""
        return self._session.get(Notification, notification_id)

    def get_by_idempotency_key(
        self,
        client_id: uuid.UUID,
        idempotency_key: str,
    ) -> Notification | None:
        """Return the existing row for this client+key, or None."""
        return self._session.scalar(
            select(Notification).where(
                Notification.client_id == client_id,
                Notification.idempotency_key == idempotency_key,
            )
        )

    def count_sent_and_failed_for_client(self, client_id: uuid.UUID) -> ClientSendCounts:
        """Return SENT/FAILED counts for ``client_id`` without loading rows."""
        stmt = select(
            func.count().filter(Notification.status == NotificationStatus.SENT),
            func.count().filter(Notification.status == NotificationStatus.FAILED),
        ).where(Notification.client_id == client_id)
        sent, failed = self._session.execute(stmt).one()
        return ClientSendCounts(sent=int(sent or 0), failed=int(failed or 0))
