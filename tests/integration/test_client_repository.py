from sqlalchemy.orm import Session

from app.core.security import generate_api_key, hash_api_key
from app.models import Client
from app.repositories import ClientRepository


def test_get_by_hashed_api_key_returns_row(db_session: Session) -> None:
    raw = generate_api_key()
    row = Client(name="checkout-app", hashed_api_key=hash_api_key(raw), is_active=True)
    db_session.add(row)
    db_session.flush()

    found = ClientRepository(db_session).get_by_hashed_api_key(hash_api_key(raw))
    assert found is not None
    assert found.id == row.id
    assert found.hashed_api_key != raw


def test_get_by_hashed_api_key_returns_none_for_unknown(db_session: Session) -> None:
    found = ClientRepository(db_session).get_by_hashed_api_key(hash_api_key("ne_nope"))
    assert found is None
