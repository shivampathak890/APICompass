"""Health check endpoint implementation."""

from datetime import datetime, timezone
from fastapi import APIRouter, status

from app.config import settings
from app.db.connection import get_db
from app.schemas.health import HealthResponse
from app.services.providers.status import get_all_provider_lifecycle_states

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Health Check",
    description="Returns the operational status, service identifier, version, current UTC timestamp, database status, and provider lifecycle states.",
)
async def get_health() -> HealthResponse:
    """Return service health status."""
    db_status = "ok"
    try:
        with get_db() as conn:
            conn.execute("SELECT 1;")
    except Exception:
        db_status = "degraded"

    return HealthResponse(
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        mock_mode=settings.MOCK_MODE,
        database_status=db_status,
        provider_status=get_all_provider_lifecycle_states(),
    )
