"""Domain layer: channels, statuses, transitions, and named errors.

This package must not import FastAPI, Pydantic, SQLAlchemy, Redis, or Celery.
"""

from app.domain.enums import Channel, NotificationStatus
from app.domain.exceptions import DomainError, InvalidStatusTransition
from app.domain.state_machine import assert_transition, can_transition, transition

__all__ = [
    "Channel",
    "DomainError",
    "InvalidStatusTransition",
    "NotificationStatus",
    "assert_transition",
    "can_transition",
    "transition",
]
