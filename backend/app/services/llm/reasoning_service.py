"""High-level LLM reasoning orchestration service for APICompass v3.

Coordinates LLM provider selection, prompt formatting, bounded input defense,
structured response validation, and generation of unverified AI suggestions.
"""

import logging
from typing import List, Optional, Set, Tuple

from app.config import settings
from app.schemas.ast_analysis import ApiCandidate, ImportInfo
from app.schemas.evidence import AISuggestion
from app.services.documentation.security import validate_destination_url
from openai import (
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
)
from app.services.llm.base import BaseLLMProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.provider import OpenAILLMProvider
from app.services.llm.schemas import (
    LLMReasoningRequest,
    LLMReasoningResponse,
)
from app.services.llm.secret_scrubber import extract_relevant_code_fragments

logger = logging.getLogger("apicompass.llm")


class LLMReasoningService:
    """Orchestrates LLM-assisted API candidate reasoning."""

    def __init__(self, override_provider: Optional[BaseLLMProvider] = None):
        self._override_provider = override_provider

    def _get_provider(self) -> Tuple[Optional[BaseLLMProvider], str]:
        """Resolve active LLM provider based on settings or override."""
        if self._override_provider is not None:
            return self._override_provider, self._override_provider.name

        provider_name = (settings.LLM_PROVIDER or "disabled").strip().lower()

        if provider_name == "disabled":
            return None, "disabled"
        elif provider_name == "mock":
            return MockLLMProvider(), "mock"
        elif provider_name == "openai":
            raw_key = settings.LLM_API_KEY
            clean_key = raw_key.strip() if raw_key and raw_key.strip() else None
            if not clean_key:
                logger.warning("OpenAI provider selected but LLM_API_KEY is not configured.")
                return None, "unavailable_missing_key"
            return (
                OpenAILLMProvider(
                    api_key=clean_key,
                    model=settings.LLM_MODEL,
                    timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
                ),
                "openai",
            )
        else:
            logger.warning("Unknown LLM_PROVIDER '%s'; defaulting to disabled.", provider_name)
            return None, "disabled"

    async def reason(
        self,
        source: str,
        filename: str,
        ecosystem: str,
        candidates: List[ApiCandidate],
        imports: List[ImportInfo],
        existing_evidence_ids: Optional[List[str]] = None,
    ) -> Tuple[LLMReasoningResponse, List[AISuggestion], List[str]]:
        """Execute LLM candidate reasoning safely.
        
        Returns:
            Tuple of:
            - LLMReasoningResponse
            - List[AISuggestion] (unverified model hypotheses)
            - List[str] (validated suggested documentation URLs)
        """
        # If no candidates exist, do not call the LLM
        if not candidates:
            return (
                LLMReasoningResponse(
                    status="disabled",
                    provider="none",
                    model="none",
                    overall_reasoning_summary="No API candidates to analyze.",
                ),
                [],
                [],
            )

        provider, provider_state = self._get_provider()

        # Handle disabled mode
        if provider_state == "disabled":
            return (
                LLMReasoningResponse(
                    status="disabled",
                    provider="disabled",
                    model="none",
                    overall_reasoning_summary="LLM reasoning is disabled (LLM_PROVIDER='disabled').",
                ),
                [],
                [],
            )

        # Handle missing key
        if provider_state == "unavailable_missing_key":
            return (
                LLMReasoningResponse(
                    status="unavailable",
                    provider="openai",
                    model=settings.LLM_MODEL,
                    error_message="LLM_API_KEY is not configured.",
                    overall_reasoning_summary="LLM reasoning is unavailable: missing API key.",
                ),
                [],
                [],
            )

        # Extract relevant code fragments, scrub secrets, and sanitize input (Requirements 2, 3, 4, 8)
        bounded_source = extract_relevant_code_fragments(
            source=source,
            candidates=candidates,
            imports=imports,
            context_lines=2,
            max_total_chars=settings.LLM_MAX_CHARS,
        )
        if not bounded_source:
            bounded_source = "# [No source code fragments extracted]"

        request = LLMReasoningRequest(
            source=bounded_source,
            filename=filename,
            ecosystem=ecosystem,
            candidates=candidates,
            imports=imports,
            existing_evidence_ids=existing_evidence_ids or [],
        )

        try:
            assert provider is not None
            response = await provider.reason_about_candidates(request)
        except (APITimeoutError, TimeoutError) as e:
            logger.error("LLM provider timed out")
            return (
                LLMReasoningResponse(
                    status="unavailable",
                    provider=provider_state,
                    model=settings.LLM_MODEL,
                    error_message=f"LLM request timed out after {settings.LLM_TIMEOUT_SECONDS}s",
                    overall_reasoning_summary="LLM reasoning is unavailable due to request timeout.",
                ),
                [],
                [],
            )
        except (AuthenticationError, RateLimitError, APIConnectionError) as e:
            logger.error("LLM provider unavailable: %s", type(e).__name__)
            return (
                LLMReasoningResponse(
                    status="unavailable",
                    provider=provider_state,
                    model=settings.LLM_MODEL,
                    error_message=f"LLM provider unavailable: {type(e).__name__}",
                    overall_reasoning_summary=f"LLM reasoning is unavailable ({type(e).__name__}).",
                ),
                [],
                [],
            )
        except Exception as e:
            logger.error("Unhandled exception in LLM provider %s: %s", provider_state, type(e).__name__)
            return (
                LLMReasoningResponse(
                    status="error",
                    provider=provider_state,
                    model=settings.LLM_MODEL,
                    error_message=f"Provider error: {type(e).__name__}",
                    overall_reasoning_summary="LLM reasoning encountered an internal provider error.",
                ),
                [],
                [],
            )

        # Server-side validation of response
        suggestions: List[AISuggestion] = []
        valid_candidate_ids = {c.candidate_id for c in candidates}
        valid_evidence_ids = set(existing_evidence_ids or [])

        suggestion_counter = 0
        for cand_reasoning in response.candidate_reasonings:
            # Enforce candidate ID authenticity
            if cand_reasoning.candidate_id not in valid_candidate_ids:
                logger.warning("Discarded model reasoning for unknown candidate_id '%s'", cand_reasoning.candidate_id)
                continue

            for claim in cand_reasoning.proposed_claims:
                if claim.affected_candidate_id not in valid_candidate_ids:
                    continue

                suggestion_counter += 1
                sug_id = f"sug_{claim.affected_candidate_id}_{suggestion_counter}"
                
                # Sanitize referenced evidence IDs
                sanitized_ev_ids = [eid for eid in claim.referenced_evidence_ids if eid in valid_evidence_ids]

                suggestions.append(
                    AISuggestion(
                        suggestion_id=sug_id,
                        candidate_id=claim.affected_candidate_id,
                        claim_type=claim.claim_type,
                        description=claim.description,
                        unverified_aspects=claim.unverified_aspects,
                        suggested_documentation_queries=cand_reasoning.suggested_documentation_queries,
                        referenced_evidence_ids=sanitized_ev_ids,
                        confidence=cand_reasoning.confidence,
                        reasoning_summary=cand_reasoning.reasoning_summary,
                        label="AI suggestion — not verified",
                    )
                )

        # Sanitize and validate suggested documentation URLs against SSRF & Allowlist
        valid_suggested_urls: Set[str] = set()
        for raw_url in response.suggested_documentation_urls:
            is_valid, canonical, _ = validate_destination_url(raw_url)
            if is_valid:
                valid_suggested_urls.add(canonical)
            else:
                logger.warning("Discarded untrusted or invalid suggested documentation URL: %s", raw_url)

        return response, suggestions, sorted(valid_suggested_urls)


# Singleton reasoning service instance
llm_service = LLMReasoningService()
