from __future__ import annotations

import uuid

import pytest

from app.services.queue import CeleryNotificationQueue, QueueUnavailableError


def test_enqueue_publishes_str_id_on_notifications_queue() -> None:
    seen: dict[str, object] = {}

    def fake_apply_async(*, args: list[str], queue: str) -> None:
        seen["args"] = args
        seen["queue"] = queue

    notification_id = uuid.uuid4()
    CeleryNotificationQueue(apply_async=fake_apply_async).enqueue(notification_id)

    assert seen["args"] == [str(notification_id)]
    assert seen["queue"] == "notifications"


def test_enqueue_wraps_broker_errors() -> None:
    def boom(*, args: list[str], queue: str) -> None:
        raise ConnectionError("broker down")

    with pytest.raises(QueueUnavailableError):
        CeleryNotificationQueue(apply_async=boom).enqueue(uuid.uuid4())
