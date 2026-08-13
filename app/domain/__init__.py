"""Domain layer: channels, statuses, transitions, and named errors.

This package must not import FastAPI, Pydantic, SQLAlchemy, Redis, or Celery.
"""

from app.domain.enums import Channel, NotificationStatus

__all__ = [
    "Channel",
    "NotificationStatus",
]
