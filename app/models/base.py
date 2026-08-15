"""Declarative metadata root. Alembic uses Base.metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared ORM base for all Mapped models."""
