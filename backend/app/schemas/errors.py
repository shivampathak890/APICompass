"""Pydantic schemas for standardized API error responses."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class ErrorDetailItem(BaseModel):
    """Structured location and message for a specific parameter or field validation failure."""
    model_config = ConfigDict(extra="forbid")

    loc: List[Union[str, int]] = Field(default_factory=list, description="Field path in request payload")
    msg: str = Field(..., description="Validation failure explanation")
    type: str = Field(default="value_error", description="Validation error category code")


class ErrorResponse(BaseModel):
    """Standardized APICompass error response schema returned for all 4xx and 5xx responses."""
    model_config = ConfigDict(extra="forbid")

    detail: str = Field(..., description="Human-readable explanation of the error (sensitive credentials scrubbed)")
    error_code: str = Field(..., description="Machine-readable error category identifier")
    status_code: int = Field(..., description="HTTP status code corresponding to the error")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of error occurrence"
    )
    errors: Optional[List[ErrorDetailItem]] = Field(
        default=None,
        description="Optional list of individual field validation errors when applicable"
    )

