"""Celery application. Broker is Redis index 1; results are ignored (Postgres wins)."""

from celery import Celery  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery("notifications_engine", include=["app.workers.tasks"])
celery_app.conf.update(
    broker_url=_settings.celery_broker_url.get_secret_value(),
    result_backend=None,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="notifications",
    task_queues=(Queue("notifications"),),
    timezone="UTC",
    enable_utc=True,
    task_acks_on_failure_or_timeout=True,
)
