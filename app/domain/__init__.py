"""Domain layer: channels, statuses, transitions, and named errors.

This package must not import FastAPI, Pydantic, SQLAlchemy, Redis, or Celery.
"""

from app.domain.enums import Channel, NotificationStatus
from app.domain.exceptions import DomainError, InvalidStatusTransition

__all__ = [
    "Channel",
    "DomainError",
    "InvalidStatusTransition",
    "NotificationStatus",
]
