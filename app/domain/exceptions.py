"""Domain errors for business-rule failures.

HTTP mapping is a later phase. Callers catch these by type, not by message text.
"""

from app.domain.enums import NotificationStatus


class DomainError(Exception):
    """Base for business-rule failures. HTTP mapping comes in a later phase."""


class InvalidStatusTransition(DomainError):
    def __init__(self, from_status: NotificationStatus, to_status: NotificationStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition from {from_status} to {to_status}"
        )
