"""FastAPI application factory and ASGI entrypoint for uvicorn."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import UnauthorizedError
from app.api.middleware.request_id import RequestIdMiddleware
from app.api.routers.clients import router as clients_router
from app.api.routers.health import router as health_router
from app.core.config import get_settings
from app.core.db import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging
from app.domain.exceptions import NotificationNotFound
from app.services.queue import QueueUnavailableError


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Configure logging and own the Postgres engine for the process lifetime."""
    settings = get_settings()
    configure_logging(settings)
    logger = logging.getLogger("app")

    engine = create_engine_from_url(settings.database_url.get_secret_value())
    application.state.engine = engine
    application.state.session_factory = create_session_factory(engine)

    logger.info("application_started", extra={"environment": settings.environment})
    yield
    engine.dispose()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Application factory so tests get a clean app instance."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(UnauthorizedError)
    async def handle_unauthorized(
        _request: Request, _exc: UnauthorizedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key", "code": "unauthorized"},
            headers={"WWW-Authenticate": "ApiKey"},
        )

    @application.exception_handler(NotificationNotFound)
    async def handle_notification_not_found(
        _request: Request, _exc: NotificationNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": "Notification not found", "code": "not_found"},
        )

    @application.exception_handler(QueueUnavailableError)
    async def handle_queue_unavailable(
        _request: Request, _exc: QueueUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Queue unavailable", "code": "service_unavailable"},
        )

    application.include_router(health_router)
    application.include_router(clients_router)
    return application


app = create_app()
