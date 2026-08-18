"""Pydantic v2 schema for client-scoped send metrics."""

from pydantic import BaseModel, Field


class ClientMetricsResponse(BaseModel):
    sent: int = Field(ge=0)
    failed: int = Field(ge=0)
