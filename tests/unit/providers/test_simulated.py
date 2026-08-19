import pytest

from app.domain.enums import Channel
from app.providers.port import (
    OutboundMessage,
    PermanentProviderError,
    TransientProviderError,
)
from app.providers.simulated import SimulatedNotificationProvider


def _message(template: str) -> OutboundMessage:
    return OutboundMessage(
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template=template,
        payload={"name": "Ada"},
    )


def test_simulated_send_returns_without_raising() -> None:
    SimulatedNotificationProvider().send(_message("welcome"))


def test_simulated_send_accepts_every_channel() -> None:
    provider = SimulatedNotificationProvider()
    for channel in Channel:
        provider.send(
            OutboundMessage(
                channel=channel,
                recipient="dest",
                template="t",
                payload={},
            )
        )


def test_fail_transient_template_raises_transient() -> None:
    with pytest.raises(TransientProviderError):
        SimulatedNotificationProvider().send(_message("fail-transient"))


def test_fail_permanent_template_raises_permanent() -> None:
    with pytest.raises(PermanentProviderError):
        SimulatedNotificationProvider().send(_message("fail-permanent"))


def test_fail_prefix_is_not_enough() -> None:
    SimulatedNotificationProvider().send(_message("fail-transient-welcome"))
