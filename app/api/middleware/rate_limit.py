"""Rate-limit POST /send before auth, validation, persist, or enqueue."""

from __future__ import annotations

import logging

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.security import hash_api_key

logger = logging.getLogger("app.rate_limit")

_SEND_PATH = "/api/v1/notifications/send"


def _bucket_key(request: Request) -> tuple[str, str]:
    """Return (redis_key, kind). kind is 'key' or 'ip' for logs; never the raw API key."""
    raw = request.headers.get("X-API-Key", "").strip()
    if raw:
        return f"rl:key:{hash_api_key(raw)}", "key"
    host = request.client.host if request.client is not None else "unknown"
    return f"rl:ip:{host}", "ip"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Spend one token on POST /send. Other routes pass through."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method != "POST" or request.url.path != _SEND_PATH:
            return await call_next(request)

        settings = get_settings()
        redis_key, kind = _bucket_key(request)
        bucket = request.app.state.token_bucket
        try:
            result = bucket.consume(
                redis_key,
                capacity=settings.rate_limit_per_minute,
            )
        except RedisError:
            logger.exception(
                "rate_limit_store_unavailable",
                extra={"kind": kind},
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Rate limiter unavailable",
                    "code": "service_unavailable",
                },
            )

        if not result.allowed:
            logger.info(
                "rate_limit_exceeded",
                extra={"kind": kind, "retry_after": result.retry_after_seconds},
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "code": "rate_limited"},
                headers={"Retry-After": str(result.retry_after_seconds)},
            )

        logger.info("rate_limit_allowed", extra={"kind": kind})
        return await call_next(request)
