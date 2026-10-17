"""API endpoint for official documentation retrieval."""

import logging
from fastapi import APIRouter, status

from app.schemas.documentation import (
    DocRetrievalRequest,
    DocRetrievalResponse,
    DocSearchRequest,
    DocSearchResponse,
)
from app.services.documentation.retrieval_service import retrieval_service

router = APIRouter(prefix="/docs", tags=["Documentation"])
logger = logging.getLogger("apicompass.docs_api")


@router.post(
    "/retrieve",
    response_model=DocRetrievalResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Official Documentation Evidence",
    description=(
        "Retrieves traceable, normalized documentation evidence from approved official sources. "
        "Operates via TinyFish in live mode or offline deterministic fixtures in mock mode. "
        "Destination URLs are strictly validated against SSRF and allowlist rules. "
        "Retrieved content is treated strictly as data and is NEVER executed."
    ),
)
async def retrieve_documentation(request: DocRetrievalRequest) -> DocRetrievalResponse:
    """Execute official documentation retrieval and return normalized evidence."""
    logger.info(
        "Received doc retrieval request: ecosystem=%s, package=%s, query=%s, target_url=%s, max_results=%d",
        request.ecosystem,
        request.package,
        request.query,
        request.target_url,
        request.max_results,
    )

    response = await retrieval_service.retrieve(request)

    logger.info(
        "Doc retrieval finished. Status=%s, Provider=%s, IsMock=%s, TotalResults=%d",
        response.status,
        response.provider,
        response.is_mock,
        response.total_results,
    )
    return response


@router.post(
    "/search",
    response_model=DocSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Candidate Official Documentation",
    description=(
        "Discovers candidate documentation pages relevant to an API symbol or query using TinyFish Search. "
        "Operates via TinyFish in live mode or offline deterministic fixtures in mock mode. "
        "INVARIANT: Search snippets are for URL discovery and ranking only, NOT verified evidence."
    ),
)
async def search_documentation(request: DocSearchRequest) -> DocSearchResponse:
    """Execute documentation search and return ranked candidate pages."""
    logger.info(
        "Received doc search request: ecosystem=%s, query=%s, limit=%d, force_mock=%s",
        request.ecosystem,
        request.query,
        request.limit,
        request.force_mock,
    )

    response = await retrieval_service.search(request)

    logger.info(
        "Doc search finished. Status=%s, Provider=%s, IsMock=%s, TotalResults=%d",
        response.status,
        response.provider,
        response.is_mock,
        response.total_results,
    )
    return response

