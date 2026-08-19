import uuid

from sqlalchemy import Engine

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import Channel, NotificationStatus
from app.domain.retry_policy import DeliveryRetryPolicy
from app.models import Client, Notification
from app.providers.port import OutboundMessage, PermanentProviderError, TransientProviderError
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchAction, DispatchService


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, message: OutboundMessage) -> None:
        self.calls += 1


class FailOnceThenSucceed:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, message: OutboundMessage) -> None:
        self.calls += 1
        if self.calls == 1:
            raise TransientProviderError("once")


class AlwaysPermanent:
    def send(self, message: OutboundMessage) -> None:
        raise PermanentProviderError("nope")


def _policy() -> DeliveryRetryPolicy:
    return DeliveryRetryPolicy(max_attempts=5, countdown_seconds=(5, 15, 45))


def test_dispatch_persists_sent_and_sent_at(persistence_engine: Engine) -> None:
    factory = create_session_factory(persistence_engine)
    provider = RecordingProvider()
    notification_id = uuid.uuid4()
    client_id: uuid.UUID
    with factory() as session:
        client = Client(
            name="dispatch-it",
            hashed_api_key=hash_api_key(generate_api_key()),
            is_active=True,
        )
        session.add(client)
        session.flush()
        client_id = client.id
        session.add(
            Notification(
                id=notification_id,
                client_id=client_id,
                channel=Channel.EMAIL,
                recipient="user@example.com",
                template="welcome",
                payload={},
                status=NotificationStatus.PENDING,
            )
        )
        session.commit()
    try:
        with factory() as session:
            service = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            )
            service.dispatch(notification_id)
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.SENT
            assert row.sent_at is not None
        assert provider.calls == 1
    finally:
        with factory() as session:
            session.delete(session.get(Notification, notification_id))
            session.delete(session.get(Client, client_id))
            session.commit()


def test_dispatch_retries_then_sends(persistence_engine: Engine) -> None:
    factory = create_session_factory(persistence_engine)
    provider = FailOnceThenSucceed()
    notification_id = uuid.uuid4()
    client_id: uuid.UUID
    with factory() as session:
        client = Client(
            name="dispatch-retry-it",
            hashed_api_key=hash_api_key(generate_api_key()),
            is_active=True,
        )
        session.add(client)
        session.flush()
        client_id = client.id
        session.add(
            Notification(
                id=notification_id,
                client_id=client_id,
                channel=Channel.EMAIL,
                recipient="user@example.com",
                template="welcome",
                payload={},
                status=NotificationStatus.PENDING,
            )
        )
        session.commit()
    try:
        with factory() as session:
            first = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            ).dispatch(notification_id)
        assert first.action is DispatchAction.RETRY
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.PENDING
            assert row.retry_count == 1
        with factory() as session:
            second = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            ).dispatch(notification_id)
        assert second.action is DispatchAction.SENT
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.SENT
            assert row.sent_at is not None
        assert provider.calls == 2
    finally:
        with factory() as session:
            session.delete(session.get(Notification, notification_id))
            session.delete(session.get(Client, client_id))
            session.commit()


def test_dispatch_permanent_failure_stays_failed(persistence_engine: Engine) -> None:
    factory = create_session_factory(persistence_engine)
    provider = AlwaysPermanent()
    notification_id = uuid.uuid4()
    client_id: uuid.UUID
    with factory() as session:
        client = Client(
            name="dispatch-perm-it",
            hashed_api_key=hash_api_key(generate_api_key()),
            is_active=True,
        )
        session.add(client)
        session.flush()
        client_id = client.id
        session.add(
            Notification(
                id=notification_id,
                client_id=client_id,
                channel=Channel.EMAIL,
                recipient="user@example.com",
                template="welcome",
                payload={},
                status=NotificationStatus.PENDING,
            )
        )
        session.commit()
    try:
        with factory() as session:
            result = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            ).dispatch(notification_id)
        assert result.action is DispatchAction.FAILED
        assert result.dead_letter is True
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.FAILED
            assert row.retry_count == 1
            assert row.sent_at is None
    finally:
        with factory() as session:
            session.delete(session.get(Notification, notification_id))
            session.delete(session.get(Client, client_id))
            session.commit()
