"""Attempt budget and backoff. Numbers come from settings; this module is stdlib-only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryRetryPolicy:
    """How many sends are allowed and how long to wait after each transient failure."""

    max_attempts: int
    countdown_seconds: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if not self.countdown_seconds or any(seconds < 1 for seconds in self.countdown_seconds):
            raise ValueError("countdown_seconds must be a non-empty tuple of ints >= 1")

    def should_retry(self, retry_count: int, *, retryable: bool) -> bool:
        """``retry_count`` is attempts already burned, including the failure just counted."""
        return retryable and retry_count < self.max_attempts

    def countdown_for(self, retry_count: int) -> int:
        """Seconds to wait after this failed attempt. Extra attempts cap at the last slot."""
        if retry_count < 1:
            raise ValueError("retry_count must be >= 1 when asking for a countdown")
        index = min(retry_count - 1, len(self.countdown_seconds) - 1)
        return self.countdown_seconds[index]
