"""In-process adapter. Logs a send; never talks to a vendor."""

from __future__ import annotations

import logging

from app.providers.port import OutboundMessage

logger = logging.getLogger("app.providers.simulated")


class SimulatedNotificationProvider:
    """v1 channel adapter: always succeeds, no network."""

    def send(self, message: OutboundMessage) -> None:
        logger.info(
            "simulated_send",
            extra={
                "channel": message.channel.value,
                "template": message.template,
            },
        )
