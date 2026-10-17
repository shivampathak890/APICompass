"""Abstract base class for documentation retrievers."""

from abc import ABC, abstractmethod
from app.schemas.documentation import (
    DocRetrievalRequest,
    DocRetrievalResponse,
    DocSearchResponse,
    NormalizedEvidence,
)


class BaseDocRetriever(ABC):
    """Abstract interface for documentation retrieval adapters."""

    @abstractmethod
    async def retrieve(self, request: DocRetrievalRequest) -> DocRetrievalResponse:
        """Execute a documentation retrieval request and return normalized evidence."""
        pass

    @abstractmethod
    async def fetch_url(self, url: str) -> NormalizedEvidence:
        """Fetch a single approved URL and return a normalized evidence record."""
        pass

    @abstractmethod
    async def search(self, query: str, ecosystem: str = "stripe", limit: int = 5) -> DocSearchResponse:
        """Search for candidate documentation pages relevant to a query or API symbol."""
        pass

