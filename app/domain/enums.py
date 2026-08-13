"""Closed sets of channels and notification statuses.

These are domain values, not HTTP or ORM types. Persistence and APIs reuse
the same strings later; they must not invent extra members.
"""

from enum import StrEnum


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
