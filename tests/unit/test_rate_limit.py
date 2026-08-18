from __future__ import annotations

import fakeredis

from app.core.rate_limit import TokenBucket

_T0 = 1_700_000_000_000


def _bucket() -> TokenBucket:
    return TokenBucket(fakeredis.FakeRedis(decode_responses=True))


def test_allows_burst_up_to_capacity() -> None:
    bucket = _bucket()
    for _ in range(10):
        result = bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
        assert result.allowed is True
    denied = bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    assert denied.allowed is False
    assert denied.retry_after_seconds >= 1


def test_keys_are_isolated() -> None:
    bucket = _bucket()
    for _ in range(10):
        bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    other = bucket.consume("rl:key:b", capacity=10, now_ms=_T0)
    assert other.allowed is True


def test_refill_allows_one_token_after_six_seconds() -> None:
    bucket = _bucket()
    for _ in range(10):
        bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    still_empty = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 1_000)
    assert still_empty.allowed is False
    refilled = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 6_000)
    assert refilled.allowed is True


def test_full_minute_restores_capacity() -> None:
    bucket = _bucket()
    for _ in range(10):
        bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    for _ in range(10):
        result = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 60_000)
        assert result.allowed is True
    denied = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 60_000)
    assert denied.allowed is False
