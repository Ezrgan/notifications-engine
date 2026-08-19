from __future__ import annotations

import pytest

from app.services.dispatch import DispatchAction, DispatchResult
from app.workers.tasks import apply_delivery_result


class FakeRetry(Exception):
    def __init__(self, countdown: int, max_retries: int) -> None:
        self.countdown = countdown
        self.max_retries = max_retries


class FakeTask:
    def retry(self, countdown: int, max_retries: int) -> None:
        raise FakeRetry(countdown, max_retries)


def test_retry_result_raises_task_retry() -> None:
    with pytest.raises(FakeRetry) as exc_info:
        apply_delivery_result(
            FakeTask(),
            DispatchResult(DispatchAction.RETRY, countdown_seconds=15),
            "nid",
            max_retries=4,
        )
    assert exc_info.value.countdown == 15
    assert exc_info.value.max_retries == 4


def test_failed_result_publishes_to_dlq_queue() -> None:
    seen: dict[str, object] = {}

    def fake_publish(*, args: list[str], queue: str) -> None:
        seen["args"] = args
        seen["queue"] = queue

    apply_delivery_result(
        FakeTask(),
        DispatchResult(DispatchAction.FAILED, dead_letter=True),
        "nid-1",
        max_retries=4,
        publish_dead_letter=fake_publish,
    )
    assert seen["args"] == ["nid-1"]
    assert seen["queue"] == "notifications.dlq"


def test_sent_result_is_a_noop() -> None:
    def boom(*, args: list[str], queue: str) -> None:
        raise AssertionError("DLQ must not run on SENT")

    apply_delivery_result(
        FakeTask(),
        DispatchResult(DispatchAction.SENT),
        "nid",
        max_retries=4,
        publish_dead_letter=boom,
    )


def test_dlq_publish_failure_is_logged_not_raised() -> None:
    def boom(*, args: list[str], queue: str) -> None:
        raise ConnectionError("broker down")

    apply_delivery_result(
        FakeTask(),
        DispatchResult(DispatchAction.FAILED, dead_letter=True),
        "nid",
        max_retries=4,
        publish_dead_letter=boom,
    )
