from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import Channel, NotificationStatus
from app.domain.exceptions import NotificationNotFound
from app.models.notification import Notification
from app.schemas.notification import SendNotificationRequest
from app.services.notification_service import NotificationService
from app.services.queue import InMemoryNotificationQueue, QueueUnavailableError


class FakeSession:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        if self.fail_commit:
            raise IntegrityError("INSERT", {}, Exception("unique"))
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.rows: list[Notification] = []

    def create(
        self,
        *,
        client_id: uuid.UUID,
        channel: Channel,
        recipient: str,
        template: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> Notification:
        row = Notification(
            id=uuid.uuid4(),
            client_id=client_id,
            channel=channel,
            recipient=recipient,
            template=template,
            payload=payload,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self.rows.append(row)
        return row

    def get_by_id_for_client(
        self,
        notification_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> Notification | None:
        for row in self.rows:
            if row.id == notification_id and row.client_id == client_id:
                return row
        return None

    def get_by_idempotency_key(
        self,
        client_id: uuid.UUID,
        idempotency_key: str,
    ) -> Notification | None:
        for row in self.rows:
            if row.client_id == client_id and row.idempotency_key == idempotency_key:
                return row
        return None


class _RaceNotificationRepository(FakeNotificationRepository):
    """First idempotency lookup misses (both racers saw None); later lookups find the winner."""

    def __init__(self) -> None:
        super().__init__()
        self._idempotency_lookups = 0

    def get_by_idempotency_key(
        self,
        client_id: uuid.UUID,
        idempotency_key: str,
    ) -> Notification | None:
        self._idempotency_lookups += 1
        if self._idempotency_lookups == 1:
            return None
        return super().get_by_idempotency_key(client_id, idempotency_key)


def _request(**overrides: object) -> SendNotificationRequest:
    data: dict[str, object] = {
        "channel": "email",
        "recipient": "user@example.com",
        "template": "welcome",
    }
    data.update(overrides)
    return SendNotificationRequest.model_validate(data)


def test_accept_persists_pending_commits_and_enqueues_once() -> None:
    session = FakeSession()
    repo = FakeNotificationRepository()
    queue = InMemoryNotificationQueue()
    service = NotificationService(session, repo, queue)
    client_id = uuid.uuid4()

    result = service.accept(client_id, _request())

    assert result.status is NotificationStatus.PENDING
    assert session.commit_calls == 1
    assert queue.enqueued == [result.notification_id]
    assert repo.rows[0].client_id == client_id


def test_accept_replay_returns_original_and_does_not_enqueue() -> None:
    session = FakeSession()
    repo = FakeNotificationRepository()
    queue = InMemoryNotificationQueue()
    service = NotificationService(session, repo, queue)
    client_id = uuid.uuid4()
    first = service.accept(
        client_id, _request(idempotency_key="checkout-99")
    )
    second = service.accept(
        client_id, _request(idempotency_key="checkout-99")
    )

    assert second.notification_id == first.notification_id
    assert queue.enqueued == [first.notification_id]
    assert session.commit_calls == 1


def test_accept_integrity_error_returns_winner_without_enqueue() -> None:
    client_id = uuid.uuid4()
    session = FakeSession(fail_commit=True)
    repo = _RaceNotificationRepository()
    winner = repo.create(
        client_id=client_id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        idempotency_key="race-1",
    )
    queue = InMemoryNotificationQueue()
    service = NotificationService(session, repo, queue)

    result = service.accept(client_id, _request(idempotency_key="race-1"))

    assert result.notification_id == winner.id
    assert session.rollback_calls == 1
    assert queue.enqueued == []


def test_accept_wraps_unexpected_queue_errors_as_unavailable() -> None:
    class BoomQueue:
        def enqueue(self, notification_id: uuid.UUID) -> None:
            raise RuntimeError("redis down")

    service = NotificationService(
        FakeSession(), FakeNotificationRepository(), BoomQueue()
    )
    with pytest.raises(QueueUnavailableError):
        service.accept(uuid.uuid4(), _request())


def test_get_status_raises_when_other_client() -> None:
    repo = FakeNotificationRepository()
    owner = uuid.uuid4()
    other = uuid.uuid4()
    row = repo.create(
        client_id=owner,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        idempotency_key=None,
    )
    service = NotificationService(FakeSession(), repo, InMemoryNotificationQueue())
    with pytest.raises(NotificationNotFound):
        service.get_status(other, row.id)
