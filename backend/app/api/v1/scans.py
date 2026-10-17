"""API endpoints for managing and inspecting historical audit scans."""

import re
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.repositories import get_scan_repository, ScanRepository
from app.schemas.scan_history import (
    ScanListResponse,
    HistoricalScanDetail,
    DeleteScanResponse,
)

router = APIRouter(prefix="/scans", tags=["Scan History"])
logger = logging.getLogger("apicompass.api.scans")

# Safe regex pattern for scan_id validation: 'scan_' followed by 8 to 64 alphanumeric characters or underscores/hyphens
SCAN_ID_PATTERN = re.compile(r"^scan_[a-zA-Z0-9_\-]{8,64}$")


def validate_scan_id(scan_id: str) -> str:
    """Validate scan_id format to prevent malformed or path traversal inputs."""
    if not SCAN_ID_PATTERN.match(scan_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid scan_id format. Must match pattern 'scan_[a-zA-Z0-9_-]{8,64}'.",
        )
    return scan_id


@router.get(
    "",
    response_model=ScanListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Historical Scans",
    description="Retrieve paginated lightweight summaries of historical scan audit records.",
)
async def list_scans(
    limit: int = Query(default=20, ge=1, le=100, description="Page size (max 100)"),
    offset: int = Query(default=0, ge=0, description="Offset from start of list"),
    verdict: Optional[str] = Query(default=None, description="Optional verdict filter: 'clean', 'issues_found', 'unable_to_verify'"),
    ecosystem: Optional[str] = Query(default=None, description="Optional ecosystem filter (e.g. 'stripe')"),
    source_sha256: Optional[str] = Query(default=None, description="Optional source SHA-256 fingerprint filter"),
    repo: ScanRepository = Depends(get_scan_repository),
) -> ScanListResponse:
    """List historical audit scans with pagination and filters."""
    # Sanitize filter inputs
    clean_verdict = verdict.strip() if verdict else None
    clean_ecosystem = ecosystem.strip() if ecosystem else None
    clean_hash = source_sha256.strip() if source_sha256 else None

    try:
        items, total = repo.list_scans(
            limit=limit,
            offset=offset,
            verdict=clean_verdict,
            ecosystem=clean_ecosystem,
            source_sha256=clean_hash,
        )
    except Exception as e:
        logger.error("Error querying historical scans: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while querying the audit scan repository.",
        )

    has_more = (offset + len(items)) < total

    return ScanListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get(
    "/{scan_id}",
    response_model=HistoricalScanDetail,
    status_code=status.HTTP_200_OK,
    summary="Get Historical Scan Audit Detail",
    description="Retrieve full audit snapshot of a previously saved scan. Does not rerun live verification.",
)
async def get_scan_detail(
    scan_id: str,
    repo: ScanRepository = Depends(get_scan_repository),
) -> HistoricalScanDetail:
    """Retrieve complete audit details for a specific historical scan."""
    validated_id = validate_scan_id(scan_id)
    try:
        scan = repo.get_scan(validated_id)
    except Exception as e:
        logger.error("Error retrieving historical scan %s: %s", validated_id, type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving the historical scan audit record.",
        )

    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Historical scan '{scan_id}' not found in audit repository.",
        )

    return scan


@router.delete(
    "/{scan_id}",
    response_model=DeleteScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Historical Scan Audit Record",
    description="Explicitly remove a historical scan and all its dependent evidence and findings records.",
)
async def delete_scan(
    scan_id: str,
    repo: ScanRepository = Depends(get_scan_repository),
) -> DeleteScanResponse:
    """Explicitly delete a historical scan by ID."""
    validated_id = validate_scan_id(scan_id)
    try:
        deleted = repo.delete_scan(validated_id)
    except Exception as e:
        logger.error("Error deleting historical scan %s: %s", validated_id, type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the historical scan audit record.",
        )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cannot delete scan '{scan_id}': record not found.",
        )

    return DeleteScanResponse(
        success=True,
        scan_id=validated_id,
        deleted_at=datetime.now(timezone.utc).isoformat(),
    )
