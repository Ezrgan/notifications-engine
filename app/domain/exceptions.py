"""Domain errors for business-rule failures.

HTTP mapping for status-machine errors is still a later phase.
NotificationNotFound is mapped in this phase because accept/status need a 404.
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


class NotificationNotFound(DomainError):
    """No notification for this client (missing or not owned). Same HTTP 404 either way."""
