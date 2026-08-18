import uuid

from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models import Client, Notification
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


def _row(
    session: Session,
    client_id: uuid.UUID,
    status: NotificationStatus,
) -> Notification:
    row = Notification(
        client_id=client_id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        status=status,
    )
    session.add(row)
    return row


def test_count_sent_and_failed_ignores_pending_and_processing(db_session: Session) -> None:
    client = _client(db_session)
    repo = NotificationRepository(db_session)
    _row(db_session, client.id, NotificationStatus.PENDING)
    _row(db_session, client.id, NotificationStatus.PENDING)
    _row(db_session, client.id, NotificationStatus.PROCESSING)
    _row(db_session, client.id, NotificationStatus.SENT)
    _row(db_session, client.id, NotificationStatus.SENT)
    _row(db_session, client.id, NotificationStatus.SENT)
    _row(db_session, client.id, NotificationStatus.FAILED)
    db_session.flush()

    counts = repo.count_sent_and_failed_for_client(client.id)
    assert counts.sent == 3
    assert counts.failed == 1


def test_count_sent_and_failed_is_zero_when_client_has_no_rows(db_session: Session) -> None:
    client = _client(db_session)
    repo = NotificationRepository(db_session)
    counts = repo.count_sent_and_failed_for_client(client.id)
    assert counts.sent == 0
    assert counts.failed == 0


def test_count_sent_and_failed_hides_other_clients_rows(db_session: Session) -> None:
    owner = _client(db_session)
    other = _client(db_session)
    repo = NotificationRepository(db_session)
    _row(db_session, owner.id, NotificationStatus.SENT)
    _row(db_session, other.id, NotificationStatus.SENT)
    _row(db_session, other.id, NotificationStatus.FAILED)
    db_session.flush()

    counts = repo.count_sent_and_failed_for_client(owner.id)
    assert counts.sent == 1
    assert counts.failed == 0
