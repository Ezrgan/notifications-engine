"""Client-scoped SENT/FAILED counts. Does not dispatch or rate-limit."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_client, get_metrics_service
from app.schemas.client import AuthenticatedClient
from app.schemas.metrics import ClientMetricsResponse
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/metrics", response_model=ClientMetricsResponse)
def read_metrics(
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
    service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> ClientMetricsResponse:
    """Return SENT/FAILED counts for the authenticated client."""
    return service.get_client_metrics(current_client.id)
