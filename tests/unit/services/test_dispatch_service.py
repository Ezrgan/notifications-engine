from __future__ import annotations

import uuid

from app.domain.enums import Channel, NotificationStatus
from app.domain.retry_policy import DeliveryRetryPolicy
from app.models.notification import Notification
from app.providers.port import (
    OutboundMessage,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from app.services.dispatch import DispatchAction, DispatchService


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


class TransientBoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise TransientProviderError("vendor 500")


class PermanentBoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise PermanentProviderError("bad recipient")


class UnclassifiedBoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise ProviderError("vendor 500")


class CrashProvider:
    def send(self, message: OutboundMessage) -> None:
        raise RuntimeError("socket exploded")


def _policy(*, max_attempts: int = 5) -> DeliveryRetryPolicy:
    return DeliveryRetryPolicy(max_attempts=max_attempts, countdown_seconds=(5, 15, 45))


def _row(
    *,
    status: NotificationStatus = NotificationStatus.PENDING,
    notification_id: uuid.UUID | None = None,
    retry_count: int = 0,
) -> Notification:
    return Notification(
        id=notification_id or uuid.uuid4(),
        client_id=uuid.uuid4(),
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"n": 1},
        status=status,
        retry_count=retry_count,
    )


def _service(
    row: Notification | None,
    provider: object,
    session: FakeSession | None = None,
    *,
    max_attempts: int = 5,
) -> tuple[DispatchService, FakeSession]:
    sess = session or FakeSession()
    service = DispatchService(
        sess,
        FakeNotificationRepository(row),
        provider,  # type: ignore[arg-type]
        _policy(max_attempts=max_attempts),
    )
    return service, sess


def test_pending_becomes_sent_and_calls_provider_once() -> None:
    row = _row()
    provider = RecordingProvider()
    service, session = _service(row, provider)

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.SENT
    assert row.status is NotificationStatus.SENT
    assert row.sent_at is not None
    assert session.commit_calls == 2
    assert len(provider.messages) == 1


def test_already_sent_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.SENT)
    provider = RecordingProvider()
    service, session = _service(row, provider)

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.SKIPPED
    assert provider.messages == []
    assert session.commit_calls == 0
    assert row.status is NotificationStatus.SENT


def test_already_failed_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.FAILED)
    provider = RecordingProvider()
    service, session = _service(row, provider)

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.SKIPPED
    assert provider.messages == []
    assert session.commit_calls == 0


def test_processing_crash_recovery_sends_without_second_pending_transition() -> None:
    row = _row(status=NotificationStatus.PROCESSING)
    provider = RecordingProvider()
    service, session = _service(row, provider)

    service.dispatch(row.id)

    assert row.status is NotificationStatus.SENT
    assert session.commit_calls == 1
    assert len(provider.messages) == 1


def test_transient_error_returns_to_pending_with_countdown() -> None:
    row = _row()
    service, session = _service(row, TransientBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert result.countdown_seconds == 5
    assert result.dead_letter is False
    assert row.status is NotificationStatus.PENDING
    assert row.retry_count == 1
    assert row.error_message == "vendor 500"
    assert row.sent_at is None
    assert session.commit_calls == 2


def test_unclassified_provider_error_is_retryable() -> None:
    row = _row()
    service, _session = _service(row, UnclassifiedBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert row.status is NotificationStatus.PENDING


def test_unexpected_exception_is_retryable() -> None:
    row = _row()
    service, _session = _service(row, CrashProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert row.retry_count == 1
    assert row.status is NotificationStatus.PENDING


def test_permanent_error_fails_without_retry() -> None:
    row = _row()
    service, session = _service(row, PermanentBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.FAILED
    assert result.dead_letter is True
    assert row.status is NotificationStatus.FAILED
    assert row.retry_count == 1
    assert row.error_message == "bad recipient"
    assert session.commit_calls == 2


def test_fifth_transient_failure_is_dead_lettered() -> None:
    row = _row(retry_count=4)
    service, _session = _service(row, TransientBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.FAILED
    assert result.dead_letter is True
    assert row.retry_count == 5
    assert row.status is NotificationStatus.FAILED


def test_fourth_retry_uses_capped_countdown() -> None:
    row = _row(retry_count=3)
    service, _session = _service(row, TransientBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert result.countdown_seconds == 45
    assert row.retry_count == 4
    assert row.status is NotificationStatus.PENDING


def test_missing_row_is_a_noop() -> None:
    provider = RecordingProvider()
    service, session = _service(None, provider)

    result = service.dispatch(uuid.uuid4())

    assert result.action is DispatchAction.MISSING
    assert provider.messages == []
    assert session.commit_calls == 0
