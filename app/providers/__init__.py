"""Channel provider adapters. v1 ships a simulated adapter behind the port."""

from app.providers.port import (
    NotificationProvider,
    OutboundMessage,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from app.providers.simulated import SimulatedNotificationProvider

__all__ = [
    "NotificationProvider",
    "OutboundMessage",
    "PermanentProviderError",
    "ProviderError",
    "SimulatedNotificationProvider",
    "TransientProviderError",
]
