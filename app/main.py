"""FastAPI application factory and ASGI entrypoint for uvicorn."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware.request_id import RequestIdMiddleware
from app.api.routers.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    """Configure logging once at startup; emit symmetric lifecycle lines."""
    settings = get_settings()
    configure_logging(settings)
    logger = logging.getLogger("app")
    logger.info("application_started", extra={"environment": settings.environment})
    yield
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
    application.include_router(health_router)
    return application


app = create_app()
