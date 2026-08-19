from app.domain.enums import Channel
from app.providers.port import OutboundMessage
from app.providers.simulated import SimulatedNotificationProvider


def test_simulated_send_returns_without_raising() -> None:
    provider = SimulatedNotificationProvider()
    provider.send(
        OutboundMessage(
            channel=Channel.EMAIL,
            recipient="user@example.com",
            template="welcome",
            payload={"name": "Ada"},
        )
    )


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
