import uuid

from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models import Client
from app.repositories import NotificationRepository


def _client(session: Session) -> Client:
    row = Client(
        name="checkout-app",
        hashed_api_key=f"dummy-hash-{uuid.uuid4().hex}",
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row


def test_create_inserts_pending_row(db_session: Session) -> None:
    client = _client(db_session)
    repo = NotificationRepository(db_session)
    row = repo.create(
        client_id=client.id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"x": 1},
        idempotency_key=None,
    )
    db_session.flush()
    assert row.status is NotificationStatus.PENDING
    assert row.payload["x"] == 1
    assert row.id is not None


def test_get_by_id_for_client_hides_other_clients_row(db_session: Session) -> None:
    owner = _client(db_session)
    other = _client(db_session)
    repo = NotificationRepository(db_session)
    row = repo.create(
        client_id=owner.id,
        channel=Channel.SMS,
        recipient="+15551234567",
        template="otp",
        payload={},
        idempotency_key="k1",
    )
    db_session.flush()
    assert repo.get_by_id_for_client(row.id, owner.id) is not None
    assert repo.get_by_id_for_client(row.id, other.id) is None
    assert repo.get_by_idempotency_key(owner.id, "k1") is not None
    assert repo.get_by_idempotency_key(other.id, "k1") is None
