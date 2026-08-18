"""Use case: read SENT/FAILED counts for the authenticated client."""

from __future__ import annotations

import logging
import uuid

from app.repositories.notification_repository import NotificationRepository
from app.schemas.metrics import ClientMetricsResponse

logger = logging.getLogger("app.metrics")


class MetricsService:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository

    def get_client_metrics(self, client_id: uuid.UUID) -> ClientMetricsResponse:
        """Return terminal send counts. Empty history is zeros, not an error."""
        counts = self._repository.count_sent_and_failed_for_client(client_id)
        logger.info(
            "metrics_read",
            extra={
                "client_id": str(client_id),
                "sent": counts.sent,
                "failed": counts.failed,
            },
        )
        return ClientMetricsResponse(sent=counts.sent, failed=counts.failed)
