"""Celery tasks. Payloads are ids; work lives in DispatchService."""

from __future__ import annotations

import uuid

from app.providers.simulated import SimulatedNotificationProvider
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchService
from app.workers.celery_app import celery_app
from app.workers.runtime import get_worker_session_factory


@celery_app.task(name="notifications.deliver", ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
def deliver_notification(notification_id: str) -> None:
    """Load the row and dispatch. Never import FastAPI routers."""
    factory = get_worker_session_factory()
    session = factory()
    try:
        service = DispatchService(
            session=session,
            repository=NotificationRepository(session),
            provider=SimulatedNotificationProvider(),
        )
        service.dispatch(uuid.UUID(notification_id))
    finally:
        session.close()
