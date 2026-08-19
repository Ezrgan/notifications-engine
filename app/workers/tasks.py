"""Celery tasks. Payloads are ids; work lives in DispatchService."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.domain.retry_policy import DeliveryRetryPolicy
from app.providers.simulated import SimulatedNotificationProvider
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchAction, DispatchResult, DispatchService
from app.workers.celery_app import celery_app
from app.workers.runtime import get_worker_session_factory

logger = logging.getLogger("app.workers.tasks")


@celery_app.task(name="notifications.dead_letter", ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
def record_dead_letter(notification_id: str) -> None:
    """Log a failed id for inspection. Never call a provider."""
    logger.warning(
        "notification_dead_lettered",
        extra={"notification_id": notification_id},
    )


def apply_delivery_result(
    task: Any,
    result: DispatchResult,
    notification_id: str,
    *,
    max_retries: int,
    publish_dead_letter: Callable[..., Any] | None = None,
) -> None:
    """Map a DispatchResult onto Celery retry or the DLQ. Tested without a live worker."""
    if result.action is DispatchAction.RETRY:
        countdown = result.countdown_seconds if result.countdown_seconds is not None else 5
        raise task.retry(countdown=countdown, max_retries=max_retries)
    if result.dead_letter:
        publish = publish_dead_letter
        if publish is None:
            publish = record_dead_letter.apply_async
        try:
            publish(args=[notification_id], queue="notifications.dlq")
        except Exception:
            logger.exception(
                "notification_dlq_publish_failed",
                extra={"notification_id": notification_id},
            )


@celery_app.task(bind=True, name="notifications.deliver", ignore_result=True)  # type: ignore[untyped-decorator]
def deliver_notification(self: Any, notification_id: str) -> None:
    """Load the row and dispatch. Never import FastAPI routers."""
    settings = get_settings()
    policy = DeliveryRetryPolicy(
        max_attempts=settings.max_delivery_attempts,
        countdown_seconds=settings.delivery_retry_countdowns,
    )
    result: DispatchResult | None = None
    factory = get_worker_session_factory()
    session = factory()
    try:
        service = DispatchService(
            session=session,
            repository=NotificationRepository(session),
            provider=SimulatedNotificationProvider(),
            policy=policy,
        )
        result = service.dispatch(uuid.UUID(notification_id))
    finally:
        session.close()
    if result is not None:
        apply_delivery_result(
            self,
            result,
            notification_id,
            max_retries=settings.max_delivery_attempts - 1,
        )
