"""API endpoints for evidence-gated fix proposals and safe static re-verification."""

import logging
from fastapi import APIRouter, status

from app.schemas.fix_proposal import FixProposalResponse, ProposeFixRequest
from app.services.fixes.fix_proposer import fix_proposer

router = APIRouter(prefix="/fixes", tags=["Fixes"])
logger = logging.getLogger("apicompass.fixes")


@router.post(
    "/propose",
    response_model=FixProposalResponse,
    status_code=status.HTTP_200_OK,
    summary="Propose Evidence-Gated Fix",
    description=(
        "Generates a safe, evidence-gated migration proposal for a selected API candidate. "
        "Applies edits in-memory only, generates a unified diff, performs static AST re-parsing, "
        "re-evaluates contracts against evidence, and reports whether the concern appears resolved. "
        "User code is never executed and local files are never overwritten."
    ),
)
async def propose_fix(request: ProposeFixRequest) -> FixProposalResponse:
    """Propose and safely re-verify an evidence-gated fix for a target candidate."""
    logger.info(
        "Received fix proposal request for candidate: %s, file: %s (length: %d chars)",
        request.candidate_id,
        request.filename,
        len(request.source),
    )

    response = await fix_proposer.propose_fix(request)

    logger.info(
        "Fix proposal completed for %s. Status: %s, SyntaxValid: %s, Reverification: %s",
        request.candidate_id,
        response.status,
        response.syntax_valid,
        response.reverification_status,
    )
    return response
