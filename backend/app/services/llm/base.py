"""Abstract base provider interface for LLM-assisted API reasoning."""

from abc import ABC, abstractmethod
from app.services.llm.schemas import LLMReasoningRequest, LLMReasoningResponse


class BaseLLMProvider(ABC):
    """Abstract interface for LLM reasoning providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'mock', 'openai')."""
        pass

    @abstractmethod
    async def reason_about_candidates(self, request: LLMReasoningRequest) -> LLMReasoningResponse:
        """Generate structured candidate interpretations and proposed claims.
        
        Args:
            request: Validated LLM reasoning request with AST candidates and bounded code.
            
        Returns:
            LLMReasoningResponse with candidate reasonings and proposed claims.
        """
        pass
