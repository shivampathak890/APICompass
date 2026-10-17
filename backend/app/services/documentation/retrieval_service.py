"""Unified documentation retrieval service.

Coordinates between the source registry, SSRF security validation,
the live TinyFish adapter, and the offline mock adapter.
"""

import logging
from typing import Optional

from app.config import settings
from app.schemas.documentation import (
    DocRetrievalRequest,
    DocRetrievalResponse,
    DocSearchRequest,
    DocSearchResponse,
)
from app.services.documentation.base import BaseDocRetriever
from app.services.documentation.mock_adapter import TinyFishMockRetriever
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever

logger = logging.getLogger("apicompass.retrieval")


class DocumentationRetrievalService:
    """Service orchestrating documentation retrieval according to active configuration."""

    def __init__(
        self,
        live_retriever: Optional[BaseDocRetriever] = None,
        mock_retriever: Optional[BaseDocRetriever] = None,
    ) -> None:
        self.live_retriever = live_retriever or TinyFishLiveRetriever()
        self.mock_retriever = mock_retriever or TinyFishMockRetriever()

    async def retrieve(self, request: DocRetrievalRequest) -> DocRetrievalResponse:
        """Execute documentation retrieval using either live TinyFish or mock fixtures.

        Guarantees:
        - Never silently substitutes mock data for failed live retrieval.
        - Clearly labels mock results with is_mock=True and status='mock'.
        - Enforces max result limits.
        """
        # Enforce conservative maximum result bounds
        if request.max_results > settings.DOC_MAX_RESULTS_LIMIT:
            request.max_results = settings.DOC_MAX_RESULTS_LIMIT

        # Determine retrieval mode: Mock vs Live
        use_mock = settings.MOCK_MODE or request.force_mock

        if use_mock:
            logger.info(
                "Executing documentation retrieval in MOCK MODE for query='%s', url='%s'",
                request.query,
                request.target_url,
            )
            return await self.mock_retriever.retrieve(request)

        # Live retrieval mode
        logger.info(
            "Executing LIVE documentation retrieval via TinyFish for query='%s', url='%s'",
            request.query,
            request.target_url,
        )
        return await self.live_retriever.retrieve(request)

    async def search(self, request: DocSearchRequest) -> DocSearchResponse:
        """Execute documentation search using either live TinyFish or mock fixtures.

        INVARIANT: Search results provide candidate URLs for downstream retrieval only.
        Snippets are not verified evidence of API contract violations.
        """
        use_mock = settings.MOCK_MODE or request.force_mock

        if use_mock:
            logger.info(
                "Executing documentation search in MOCK MODE for query='%s', limit=%d",
                request.query,
                request.limit,
            )
            return await self.mock_retriever.search(
                query=request.query,
                ecosystem=request.ecosystem,
                limit=request.limit,
            )

        logger.info(
            "Executing LIVE documentation search via TinyFish for query='%s', limit=%d",
            request.query,
            request.limit,
        )
        return await self.live_retriever.search(
            query=request.query,
            ecosystem=request.ecosystem,
            limit=request.limit,
        )



# Singleton service instance
retrieval_service = DocumentationRetrievalService()
