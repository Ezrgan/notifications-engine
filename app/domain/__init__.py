"""Domain layer: channels, statuses, transitions, and named errors.

This package must not import FastAPI, Pydantic, SQLAlchemy, Redis, or Celery.
"""

from app.domain.enums import Channel, NotificationStatus
from app.domain.exceptions import DomainError, InvalidStatusTransition, NotificationNotFound
from app.domain.retry_policy import DeliveryRetryPolicy
from app.domain.state_machine import assert_transition, can_transition, transition

__all__ = [
    "Channel",
    "DeliveryRetryPolicy",
    "DomainError",
    "InvalidStatusTransition",
    "NotificationNotFound",
    "NotificationStatus",
    "assert_transition",
    "can_transition",
    "transition",
]
