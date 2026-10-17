from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Health check response model."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="Overall health status", examples=["healthy"])
    service: str = Field(..., description="Service identifier", examples=["apicompass-api"])
    version: str = Field(..., description="Service semantic version", examples=["0.1.0"])
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp of the health check")
    mock_mode: bool = Field(default=True, description="Whether the system is operating in mock mode")
    database_status: Optional[str] = Field(default="ok", description="Status of local SQLite audit repository ('ok', 'degraded')")
    provider_status: Optional[dict[str, str]] = Field(default=None, description="Diagnostic lifecycle states of external providers")
