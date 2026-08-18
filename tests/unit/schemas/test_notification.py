import pytest
from pydantic import ValidationError

from app.domain.enums import Channel
from app.schemas.notification import SendNotificationRequest


def test_send_request_accepts_minimal_email_body() -> None:
    body = SendNotificationRequest.model_validate(
        {
            "channel": "email",
            "recipient": "user@example.com",
            "template": "welcome",
        }
    )
    assert body.channel is Channel.EMAIL
    assert body.payload == {}
    assert body.idempotency_key is None


def test_send_request_rejects_unknown_channel() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "fax",
                "recipient": "user@example.com",
                "template": "welcome",
            }
        )


def test_send_request_rejects_uppercase_channel_token() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "EMAIL",
                "recipient": "user@example.com",
                "template": "welcome",
            }
        )


def test_send_request_rejects_empty_recipient() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "sms",
                "recipient": "",
                "template": "otp",
            }
        )


def test_send_request_rejects_empty_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "email",
                "recipient": "user@example.com",
                "template": "welcome",
                "idempotency_key": "",
            }
        )


def test_send_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "email",
                "recipient": "user@example.com",
                "template": "welcome",
                "from": "nope",
            }
        )
