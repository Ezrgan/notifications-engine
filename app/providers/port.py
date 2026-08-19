"""Application-owned provider port.

Workers call this; routers must not. Retry policy lives in the worker (later),
not inside an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.enums import Channel


class ProviderError(Exception):
    """The channel adapter could not deliver. Dispatch maps this to FAILED."""


@dataclass(frozen=True)
class OutboundMessage:
    """What the provider needs to deliver. No ORM, no HTTP, no API key."""

    channel: Channel
    recipient: str
    template: str
    payload: dict[str, Any]


class NotificationProvider(Protocol):
    """Port: send one already-accepted notification payload."""

    def send(self, message: OutboundMessage) -> None:
        """Deliver ``message``. Raise ``ProviderError`` on failure. Return None on success."""
        ...
