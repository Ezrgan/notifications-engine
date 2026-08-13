"""Legal and illegal notification status transitions."""

import pytest

from app.domain.enums import NotificationStatus
from app.domain.exceptions import InvalidStatusTransition
from app.domain.state_machine import assert_transition, can_transition, transition

PENDING = NotificationStatus.PENDING
PROCESSING = NotificationStatus.PROCESSING
SENT = NotificationStatus.SENT
FAILED = NotificationStatus.FAILED


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (PENDING, PROCESSING),
        (PROCESSING, SENT),
        (PROCESSING, FAILED),
        (PROCESSING, PENDING),
    ],
)
def test_legal_transition_is_allowed_and_returns_dst(
    src: NotificationStatus,
    dst: NotificationStatus,
) -> None:
    assert can_transition(src, dst) is True
    assert_transition(src, dst)
    assert transition(src, dst) is dst


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (SENT, PENDING),
        (FAILED, SENT),
        (PENDING, SENT),
        (PENDING, FAILED),
        (SENT, SENT),
        (FAILED, PROCESSING),
        (PENDING, PENDING),
    ],
)
def test_illegal_transition_raises_named_error(
    src: NotificationStatus,
    dst: NotificationStatus,
) -> None:
    assert can_transition(src, dst) is False
    with pytest.raises(InvalidStatusTransition) as exc_info:
        transition(src, dst)
    error = exc_info.value
    assert error.from_status is src
    assert error.to_status is dst


def test_sent_to_pending_exposes_from_and_to_status() -> None:
    with pytest.raises(InvalidStatusTransition) as exc_info:
        assert_transition(SENT, PENDING)
    error = exc_info.value
    assert error.from_status is SENT
    assert error.to_status is PENDING
