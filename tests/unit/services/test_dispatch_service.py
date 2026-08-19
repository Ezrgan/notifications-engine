from __future__ import annotations

import uuid

from app.domain.enums import Channel, NotificationStatus
from app.models.notification import Notification
from app.providers.port import OutboundMessage, ProviderError
from app.services.dispatch import DispatchService


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1


class FakeNotificationRepository:
    def __init__(self, row: Notification | None) -> None:
        self.row = row

    def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        if self.row is None or self.row.id != notification_id:
            return None
        return self.row


class RecordingProvider:
    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    def send(self, message: OutboundMessage) -> None:
        self.messages.append(message)


class BoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise ProviderError("vendor 500")


class CrashProvider:
    def send(self, message: OutboundMessage) -> None:
        raise RuntimeError("socket exploded")


def _row(
    *,
    status: NotificationStatus = NotificationStatus.PENDING,
    notification_id: uuid.UUID | None = None,
) -> Notification:
    return Notification(
        id=notification_id or uuid.uuid4(),
        client_id=uuid.uuid4(),
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"n": 1},
        status=status,
        retry_count=0,
    )


def test_pending_becomes_sent_and_calls_provider_once() -> None:
    row = _row()
    session = FakeSession()
    provider = RecordingProvider()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert row.status is NotificationStatus.SENT
    assert row.sent_at is not None
    assert session.commit_calls == 2
    assert len(provider.messages) == 1
    assert provider.messages[0].template == "welcome"


def test_already_sent_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.SENT)
    provider = RecordingProvider()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert provider.messages == []
    assert session.commit_calls == 0
    assert row.status is NotificationStatus.SENT


def test_already_failed_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.FAILED)
    provider = RecordingProvider()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert provider.messages == []
    assert session.commit_calls == 0


def test_processing_crash_recovery_sends_without_second_pending_transition() -> None:
    row = _row(status=NotificationStatus.PROCESSING)
    provider = RecordingProvider()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert row.status is NotificationStatus.SENT
    assert session.commit_calls == 1
    assert len(provider.messages) == 1


def test_provider_error_marks_failed() -> None:
    row = _row()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), BoomProvider())

    service.dispatch(row.id)

    assert row.status is NotificationStatus.FAILED
    assert row.error_message == "vendor 500"
    assert row.sent_at is None
    assert session.commit_calls == 2


def test_unexpected_provider_exception_marks_failed() -> None:
    row = _row()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), CrashProvider())

    service.dispatch(row.id)

    assert row.status is NotificationStatus.FAILED
    assert row.error_message == "socket exploded"
    assert row.sent_at is None
    assert session.commit_calls == 2


def test_missing_row_is_a_noop() -> None:
    session = FakeSession()
    provider = RecordingProvider()
    service = DispatchService(session, FakeNotificationRepository(None), provider)

    service.dispatch(uuid.uuid4())

    assert provider.messages == []
    assert session.commit_calls == 0
