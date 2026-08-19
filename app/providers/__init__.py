"""Channel provider adapters. v1 ships a simulated adapter behind the port."""

from app.providers.port import NotificationProvider, OutboundMessage, ProviderError
from app.providers.simulated import SimulatedNotificationProvider

__all__ = [
    "NotificationProvider",
    "OutboundMessage",
    "ProviderError",
    "SimulatedNotificationProvider",
]
