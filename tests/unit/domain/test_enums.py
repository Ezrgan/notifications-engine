"""Closed-set contracts for Channel and NotificationStatus."""

from app.domain.enums import Channel, NotificationStatus


def test_channel_has_exactly_four_members() -> None:
    assert list(Channel) == [
        Channel.EMAIL,
        Channel.SMS,
        Channel.PUSH,
        Channel.WEBHOOK,
    ]


def test_notification_status_has_exactly_four_members() -> None:
    assert list(NotificationStatus) == [
        NotificationStatus.PENDING,
        NotificationStatus.PROCESSING,
        NotificationStatus.SENT,
        NotificationStatus.FAILED,
    ]


def test_channel_email_equals_lowercase_string() -> None:
    assert Channel.EMAIL == "email"


def test_notification_status_sent_equals_uppercase_string() -> None:
    assert NotificationStatus.SENT == "SENT"
