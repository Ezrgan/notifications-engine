"""Pydantic v2 schemas for notification accept and status."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Channel, NotificationStatus


class SendNotificationRequest(BaseModel):
    """Body for POST /send. extra=forbid so typos fail 422 instead of being dropped."""

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    recipient: str = Field(min_length=1, max_length=320)
    template: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class SendAcceptedResponse(BaseModel):
    notification_id: uuid.UUID
    status: NotificationStatus


class NotificationStatusResponse(BaseModel):
    notification_id: uuid.UUID
    status: NotificationStatus
