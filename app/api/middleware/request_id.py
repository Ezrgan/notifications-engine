"""HTTP middleware that assigns and echoes X-Request-ID."""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx

_HEADER_NAME = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate a request id via ContextVar and response header."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming = request.headers.get(_HEADER_NAME, "").strip()
        request_id = incoming if incoming else str(uuid4())
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers[_HEADER_NAME] = request_id
        return response
