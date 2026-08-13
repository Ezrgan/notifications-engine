"""Legal notification status transitions.

A table, not a configurable graph: v1 has four statuses and four allowed
edges. Functions are pure — they return a status or raise; they do not
mutate a notification entity (that entity does not exist yet).
"""

from app.domain.enums import NotificationStatus
from app.domain.exceptions import InvalidStatusTransition

_ALLOWED: dict[NotificationStatus, frozenset[NotificationStatus]] = {
    NotificationStatus.PENDING: frozenset({NotificationStatus.PROCESSING}),
    NotificationStatus.PROCESSING: frozenset(
        {
            NotificationStatus.SENT,
            NotificationStatus.FAILED,
            NotificationStatus.PENDING,
        }
    ),
    NotificationStatus.SENT: frozenset(),
    NotificationStatus.FAILED: frozenset(),
}


def can_transition(src: NotificationStatus, dst: NotificationStatus) -> bool:
    """Return True if ``src → dst`` is in the frozen table."""
    return dst in _ALLOWED[src]


def assert_transition(src: NotificationStatus, dst: NotificationStatus) -> None:
    """Raise ``InvalidStatusTransition`` when ``src → dst`` is illegal."""
    if not can_transition(src, dst):
        raise InvalidStatusTransition(src, dst)


def transition(src: NotificationStatus, dst: NotificationStatus) -> NotificationStatus:
    """Return ``dst`` when the edge is legal; otherwise raise."""
    assert_transition(src, dst)
    return dst
