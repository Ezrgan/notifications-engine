"""In-process adapter. Logs a send; never talks to a vendor."""

from __future__ import annotations

import logging

from app.providers.port import (
    OutboundMessage,
    PermanentProviderError,
    TransientProviderError,
)

logger = logging.getLogger("app.providers.simulated")

_TRANSIENT_FAIL_TEMPLATE = "fail-transient"
_PERMANENT_FAIL_TEMPLATE = "fail-permanent"


class SimulatedNotificationProvider:
    """v1 channel adapter: succeeds unless the template is an exact fail switch."""

    def send(self, message: OutboundMessage) -> None:
        if message.template == _PERMANENT_FAIL_TEMPLATE:
            raise PermanentProviderError("simulated permanent failure")
        if message.template == _TRANSIENT_FAIL_TEMPLATE:
            raise TransientProviderError("simulated transient failure")
        logger.info(
            "simulated_send",
            extra={
                "channel": message.channel.value,
                "template": message.template,
            },
        )
