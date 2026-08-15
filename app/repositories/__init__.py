"""Persistence adapters: repository implementations."""

from app.repositories.client_repository import ClientRepository
from app.repositories.notification_repository import NotificationRepository

__all__ = ["ClientRepository", "NotificationRepository"]
