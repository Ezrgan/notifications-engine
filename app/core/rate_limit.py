"""Atomic Token Bucket stored in Redis.

Callers pass a already-hashed identity (API-key hash or IP). This module never
sees a raw API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_LUA_CONSUME = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local period_ms = tonumber(ARGV[3])
local take = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then
  elapsed = 0
end

local refill = elapsed * (capacity / period_ms)
tokens = math.min(capacity, tokens + refill)
ts = now

local allowed = 0
local retry_after = 0

-- A denied probe can split one refill into two adds; IEEE 754 may land at 0.999...
if tokens + 1e-9 >= take then
  tokens = tokens - take
  if tokens < 0 then
    tokens = 0
  end
  allowed = 1
else
  allowed = 0
  local missing = take - tokens
  local rate = capacity / period_ms
  retry_after = math.ceil(missing / rate / 1000)
  if retry_after < 1 then
    retry_after = 1
  end
end

redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
redis.call('PEXPIRE', key, period_ms * 2)
return {allowed, retry_after}
"""


@dataclass(frozen=True)
class TokenBucketResult:
    """Outcome of one consume attempt."""

    allowed: bool
    retry_after_seconds: int


class TokenBucket:
    """Consume tokens from a Redis hash using one EVAL (no GET/SET race)."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        self._consume = redis_client.register_script(_LUA_CONSUME)

    def consume(
        self,
        key: str,
        *,
        capacity: int,
        refill_period_ms: int = 60_000,
        now_ms: int | None = None,
    ) -> TokenBucketResult:
        """Take one token from ``key``. ``now_ms`` is injectable so tests never sleep."""
        if now_ms is None:
            now_ms = int(self._redis.time()[0] * 1000)
        allowed, retry_after = self._consume(
            keys=[key],
            args=[now_ms, capacity, refill_period_ms, 1],
        )
        return TokenBucketResult(
            allowed=bool(int(allowed)),
            retry_after_seconds=int(retry_after),
        )
