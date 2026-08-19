import uuid

from sqlalchemy import Engine

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import Channel, NotificationStatus
from app.models import Client, Notification
from app.providers.port import OutboundMessage
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchService


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, message: OutboundMessage) -> None:
        self.calls += 1


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
                session, NotificationRepository(session), provider
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
