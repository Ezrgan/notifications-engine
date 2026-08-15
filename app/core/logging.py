"""Structured logging for the application process.

Uses stdlib logging only. Local/test emit a single-line text format; production
emits one JSON object per record. Correlation fields (request_id and later
notification_id, etc.) ride on the LogRecord via Filter + `extra=`.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED_EXTRA_FIELDS = (
    "notification_id",
    "client_id",
    "channel",
    "status",
    "retry_count",
)

_CONFIGURED_MARKER = "notifications_engine_configured"


class RequestIdFilter(logging.Filter):
    """Copy the ContextVar request id onto every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class TextFormatter(logging.Formatter):
    """Human-readable one-line format for local and test environments."""

    def format(self, record: logging.LogRecord) -> str:
        asctime = self.formatTime(record, self.datefmt)
        request_id = getattr(record, "request_id", "-")
        base = (
            f"{asctime} {record.levelname} {record.name} "
            f"request_id={request_id} {record.getMessage()}"
        )
        extras = _format_extra_kv(record)
        if extras:
            return f"{base} {extras}"
        return base


class JsonFormatter(logging.Formatter):
    """One JSON object per line for production stdout collectors."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in _RESERVED_EXTRA_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=True, default=str)


def _format_extra_kv(record: logging.LogRecord) -> str:
    parts: list[str] = []
    for key in _RESERVED_EXTRA_FIELDS:
        if hasattr(record, key):
            parts.append(f"{key}={getattr(record, key)}")
    return " ".join(parts)


def configure_logging(settings: Settings) -> None:
    """Configure root logging once; safe to call again without duplicating handlers."""
    root = logging.getLogger()
    if root.handlers and getattr(root, _CONFIGURED_MARKER, False):
        # Idempotent path: wipe and rebuild so level/formatter stay in sync.
        root.handlers.clear()

    root.handlers.clear()
    root.setLevel(settings.log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.log_level)
    handler.addFilter(RequestIdFilter())
    if settings.environment == "production":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)
    setattr(root, _CONFIGURED_MARKER, True)

    # Alembic's fileConfig can leave named loggers disabled; re-enable ours.
    logging.getLogger("app").disabled = False

    # Keep noisy libraries quieter than our app logger by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
