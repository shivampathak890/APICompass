"""TinyFish documentation retrieval adapter.

Connects to the official TinyFish Fetch & Search APIs to retrieve live documentation.
Enforces finite timeouts, SSRF destination validation, sanitized response parsing,
and graceful fallback when credentials are missing or errors occur.
"""

import asyncio
from datetime import datetime, timezone
import logging
import random
import time
from typing import Awaitable, Callable, List, Optional, Tuple
import httpx

from app.config import settings
from app.schemas.documentation import (
    DocRetrievalRequest,
    DocRetrievalResponse,
    DocSearchResponse,
    NormalizedEvidence,
    SearchResultItem,
)
from app.services.documentation.base import BaseDocRetriever
from app.services.documentation.circuit_breaker import CircuitBreaker
from app.services.documentation.mock_adapter import compute_evidence_id
from app.services.documentation.registry import (
    resolve_documentation_target,
    resolve_documentation_target_async,
)
from app.services.documentation.normalizer import normalize_documentation_content
from app.services.documentation.security import validate_destination_url

logger = logging.getLogger("apicompass.tinyfish")


_CONFIG_DEFAULT = object()


class TinyFishLiveRetriever(BaseDocRetriever):
    """Live documentation retriever using TinyFish APIs."""

    def __init__(
        self,
        api_key: Optional[str] = _CONFIG_DEFAULT,  # type: ignore
        search_base_url: Optional[str] = None,
        fetch_base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
        base_backoff_seconds: Optional[float] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        sleep_fn: Optional[Callable[[float], Awaitable[None]]] = None,
        time_fn: Optional[Callable[[], float]] = None,
        jitter_fn: Optional[Callable[[int], float]] = None,
    ) -> None:
        if api_key is _CONFIG_DEFAULT:
            self._api_key = _CONFIG_DEFAULT
        else:
            self._api_key = api_key.strip() if api_key and api_key.strip() else ""
        self.search_base_url = search_base_url or settings.TINYFISH_SEARCH_BASE_URL
        self.fetch_base_url = fetch_base_url or settings.TINYFISH_FETCH_BASE_URL
        self.timeout = timeout_seconds or settings.DOC_RETRIEVAL_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.DOC_RETRIEVAL_MAX_RETRIES
        self.base_backoff_seconds = (
            base_backoff_seconds
            if base_backoff_seconds is not None
            else settings.DOC_RETRIEVAL_BASE_BACKOFF_SECONDS
        )
        self._time_fn = time_fn or time.monotonic
        self._sleep_fn = sleep_fn or asyncio.sleep
        self._jitter_fn = jitter_fn
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=settings.DOC_CIRCUIT_BREAKER_FAILURES,
            recovery_timeout_seconds=settings.DOC_CIRCUIT_BREAKER_RECOVERY_SECONDS,
            time_fn=self._time_fn,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Dynamic API key lookup falling back to current settings.TINYFISH_API_KEY only when unset."""
        if self._api_key is _CONFIG_DEFAULT:
            raw_key = settings.TINYFISH_API_KEY
            return raw_key.strip() if raw_key and raw_key.strip() else None
        return self._api_key if self._api_key else None

    @api_key.setter
    def api_key(self, value: Optional[str]) -> None:
        if value is _CONFIG_DEFAULT:
            self._api_key = _CONFIG_DEFAULT
        else:
            self._api_key = value.strip() if value and value.strip() else ""

    def _calculate_backoff(
        self, attempt: int, retry_after_header: Optional[str] = None
    ) -> Tuple[float, bool]:
        """Calculate retry backoff with defensive Retry-After parsing and bounded jitter.

        Returns:
            (backoff_seconds: float, should_abort: bool)
        """
        if retry_after_header is not None:
            try:
                ra = float(retry_after_header)
                if ra > 2.0:
                    # Ceil of 2.0s exceeded: abort immediately to avoid blocking
                    return 0.0, True
                elif 0.0 < ra <= 2.0:
                    return ra, False
                # If ra <= 0.0, fall through to calculated exponential backoff
            except (ValueError, TypeError):
                # Malformed header: fall through to calculated exponential backoff
                pass

        base = self.base_backoff_seconds * (2 ** attempt)
        if self._jitter_fn is not None:
            jitter = self._jitter_fn(attempt)
        else:
            jitter = random.uniform(0.0, 0.02)
        return base + max(0.0, jitter), False

    def _get_headers(self) -> dict:
        """Construct request headers without logging the secret key."""
        return {
            "X-API-Key": self.api_key or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"APICompass/{settings.APP_VERSION}",
        }

    async def fetch_url(self, url: str) -> NormalizedEvidence:
        """Fetch content for a single validated documentation URL via TinyFish Fetch API."""
        now_utc = datetime.now(timezone.utc).isoformat()

        # Step 1: Pre-flight security & SSRF validation (Never retry)
        is_valid, canonical_url, err = validate_destination_url(url)
        if not is_valid:
            logger.warning("SSRF / security rejection for target URL '%s': %s", url, err)
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(url, "rejected"),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=canonical_url or url,
                title=None,
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_live",
                status="rejected",
                is_mock=False,
                source_trust="untrusted",
                doc_version=None,
                error_code="SSRF_POLICY_VIOLATION",
                error_message=err,
            )

        # Step 2: Ensure credentials exist (Never retry)
        if not self.api_key:
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(canonical_url, "missing_key"),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=canonical_url,
                title=None,
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_live",
                status="unavailable",
                is_mock=False,
                source_trust="official",
                doc_version=None,
                error_code="CREDENTIALS_MISSING",
                error_message="TinyFish API key (TINYFISH_API_KEY) is not configured.",
            )

        # Step 3: Check circuit breaker state (Fast-fail when open)
        is_probe = (self.circuit_breaker.state == "half_open")
        if not self.circuit_breaker.can_execute():
            logger.warning("TinyFish circuit breaker is %s; rejecting fetch for '%s'", self.circuit_breaker.state, canonical_url)
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(canonical_url, "circuit_open"),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=canonical_url,
                title=None,
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_live",
                status="unavailable",
                is_mock=False,
                source_trust="official",
                doc_version=None,
                error_code="CIRCUIT_OPEN",
                error_message="TinyFish circuit breaker is OPEN due to repeated transient failures.",
            )

        # Step 4: Bounded retries for idempotent documentation retrieval
        start_time = self._time_fn()
        overall_budget = self.timeout
        max_attempts = 1 + max(0, self.max_retries)
        last_error_code = "NETWORK_ERROR"
        last_error_message = "A network error occurred while communicating with TinyFish."
        recorded_outcome = False

        try:
            for attempt in range(max_attempts):
                elapsed = self._time_fn() - start_time
                remaining_budget = overall_budget - elapsed
                if remaining_budget <= 0:
                    self.circuit_breaker.record_failure()
                    recorded_outcome = True
                    return NormalizedEvidence(
                        evidence_id=compute_evidence_id(canonical_url, "timeout"),
                        ecosystem="stripe",
                        package="stripe",
                        source_url=url,
                        canonical_url=canonical_url,
                        title=None,
                        content_excerpt="",
                        retrieved_at=now_utc,
                        provider="tinyfish_live",
                        status="unavailable",
                        is_mock=False,
                        source_trust="official",
                        error_code="TIMEOUT",
                        error_message=f"Request to TinyFish timed out after {self.timeout}s.",
                    )

                # Clamp attempt timeout to remaining overall budget
                attempt_timeout = remaining_budget
                timeout = httpx.Timeout(attempt_timeout, connect=min(5.0, attempt_timeout))

                try:
                    fetch_payload = {"urls": [canonical_url]}

                    async with asyncio.timeout(attempt_timeout):
                        async with httpx.AsyncClient(timeout=timeout) as client:
                            response = await client.post(
                                self.fetch_base_url,
                                headers=self._get_headers(),
                                json=fetch_payload,
                            )

                    # Check response size limit (10MB)
                    if len(response.content) > 10 * 1024 * 1024:
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "oversized_response"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="RESPONSE_TOO_LARGE",
                            error_message="Documentation response exceeded maximum size limit of 10MB.",
                        )

                    # Non-retryable: Auth / Permissions (401, 403)
                    if response.status_code in (401, 403):
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "auth_failure"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="AUTHENTICATION_FAILED",
                            error_message="TinyFish authentication failed. Check TINYFISH_API_KEY.",
                        )

                    # Non-retryable: Rate limiting (429) - avoid retry storms
                    if response.status_code == 429:
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "rate_limited"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="RATE_LIMITED",
                            error_message="TinyFish rate limit reached. Please retry later.",
                        )

                    # Transient server errors: 502, 503, 504 (Retryable)
                    if response.status_code in (502, 503, 504):
                        last_error_code = "PROVIDER_ERROR"
                        last_error_message = f"TinyFish service returned HTTP {response.status_code}"

                        if attempt < max_attempts - 1:
                            retry_after_str = response.headers.get("retry-after")
                            backoff, should_abort = self._calculate_backoff(attempt, retry_after_str)
                            if should_abort:
                                break

                            elapsed_now = self._time_fn() - start_time
                            if elapsed_now + backoff < overall_budget:
                                logger.info(
                                    "Transient HTTP %d from TinyFish; retrying in %.2fs (attempt %d/%d)",
                                    response.status_code,
                                    backoff,
                                    attempt + 1,
                                    max_attempts,
                                )
                                await self._sleep_fn(backoff)
                                continue
                            else:
                                last_error_code = "TIMEOUT"
                                last_error_message = f"Request to TinyFish timed out after {self.timeout}s."
                        break

                    # Non-retryable provider errors (400, 404, 500, etc.)
                    if response.status_code != 200:
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "provider_error"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="PROVIDER_ERROR",
                            error_message=f"TinyFish service returned HTTP {response.status_code}",
                        )

                    # JSON parsing (Non-retryable on malformed response)
                    try:
                        payload = response.json()
                    except Exception:
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "invalid_json"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="INVALID_RESPONSE_JSON",
                            error_message="Provider response could not be parsed as JSON.",
                        )

                    # Check for top-level upstream errors array
                    errors = payload.get("errors")
                    if isinstance(errors, list) and len(errors) > 0:
                        err_item = errors[0]
                        err_code = err_item.get("error_code") or "PROVIDER_ERROR"
                        err_msg = err_item.get("error_message") or f"TinyFish failed to extract documentation for {canonical_url}"
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, err_code.lower()),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code=err_code,
                            error_message=err_msg,
                        )

                    # Results validation
                    results = payload.get("results")
                    if not isinstance(results, list) or len(results) == 0:
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "empty_results"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="NO_CONTENT_RETURNED",
                            error_message="TinyFish returned zero results for the target URL.",
                        )

                    page_data = results[0]
                    if page_data.get("status") == "failed":
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(canonical_url, "extraction_failed"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=url,
                            canonical_url=canonical_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="unavailable",
                            is_mock=False,
                            source_trust="official",
                            error_code="EXTRACTION_FAILED",
                            error_message="TinyFish page extraction failed.",
                        )

                    returned_url = page_data.get("final_url") or page_data.get("url") or canonical_url

                    # Post-fetch redirect escape check (Non-retryable)
                    is_ret_valid, verified_ret_url, ret_err = validate_destination_url(returned_url)
                    if not is_ret_valid:
                        return NormalizedEvidence(
                            evidence_id=compute_evidence_id(returned_url, "redirect_rejected"),
                            ecosystem="stripe",
                            package="stripe",
                            source_url=returned_url,
                            canonical_url=verified_ret_url or returned_url,
                            title=None,
                            content_excerpt="",
                            retrieved_at=now_utc,
                            provider="tinyfish_live",
                            status="rejected",
                            is_mock=False,
                            source_trust="untrusted",
                            error_code="REDIRECT_ESCAPE_VIOLATION",
                            error_message=f"Returned destination failed validation: {ret_err}",
                        )

                    title = page_data.get("title")
                    raw_text = page_data.get("text") or page_data.get("content") or ""

                    # Normalize documentation content
                    page_model, cleaned_text = normalize_documentation_content(
                        raw_text=raw_text,
                        url=url,
                        final_url=verified_ret_url,
                        title=title,
                        doc_version=page_data.get("doc_version"),
                        provider="tinyfish_live",
                        is_mock=False,
                        retrieved_at=now_utc,
                    )

                    # Success! Record success in circuit breaker
                    self.circuit_breaker.record_success()
                    recorded_outcome = True

                    return NormalizedEvidence(
                        evidence_id=compute_evidence_id(verified_ret_url, cleaned_text),
                        ecosystem="stripe",
                        package="stripe",
                        source_url=returned_url,
                        canonical_url=verified_ret_url,
                        title=title,
                        content_excerpt=cleaned_text,
                        retrieved_at=now_utc,
                        provider="tinyfish_live",
                        status="success",
                        is_mock=False,
                        source_trust="official",
                        doc_version=page_data.get("doc_version"),
                        error_code=None,
                        error_message=None,
                        raw_markdown=page_model.content,
                        content_sha256=page_model.content_sha256,
                        headings=page_model.headings,
                        parameters=page_model.parameters,
                        required_fields=page_model.required_fields,
                        deprecation_notices=page_model.deprecation_notices,
                        code_examples=page_model.code_examples,
                        page_data=page_model,
                    )

                except (httpx.TimeoutException, TimeoutError):
                    last_error_code = "TIMEOUT"
                    last_error_message = f"Request to TinyFish timed out after {self.timeout}s."
                    if attempt < max_attempts - 1:
                        backoff, should_abort = self._calculate_backoff(attempt)
                        if should_abort:
                            break
                        elapsed_now = self._time_fn() - start_time
                        if elapsed_now + backoff < overall_budget:
                            logger.info(
                                "Timeout from TinyFish; retrying in %.2fs (attempt %d/%d)",
                                backoff,
                                attempt + 1,
                                max_attempts,
                            )
                            await self._sleep_fn(backoff)
                            continue
                        else:
                            last_error_code = "TIMEOUT"
                            last_error_message = f"Request to TinyFish timed out after {self.timeout}s."
                    break

                except (httpx.NetworkError, ConnectionResetError):
                    last_error_code = "NETWORK_ERROR"
                    last_error_message = "A network error occurred while communicating with TinyFish."
                    if attempt < max_attempts - 1:
                        backoff, should_abort = self._calculate_backoff(attempt)
                        if should_abort:
                            break
                        elapsed_now = self._time_fn() - start_time
                        if elapsed_now + backoff < overall_budget:
                            logger.info(
                                "Connection error from TinyFish; retrying in %.2fs (attempt %d/%d)",
                                backoff,
                                attempt + 1,
                                max_attempts,
                            )
                            await self._sleep_fn(backoff)
                            continue
                        else:
                            last_error_code = "TIMEOUT"
                            last_error_message = f"Request to TinyFish timed out after {self.timeout}s."
                    break

                except asyncio.CancelledError:
                    raise

                except Exception:
                    self.circuit_breaker.record_failure()
                    recorded_outcome = True
                    return NormalizedEvidence(
                        evidence_id=compute_evidence_id(canonical_url, "network_error"),
                        ecosystem="stripe",
                        package="stripe",
                        source_url=url,
                        canonical_url=canonical_url,
                        title=None,
                        content_excerpt="",
                        retrieved_at=now_utc,
                        provider="tinyfish_live",
                        status="unavailable",
                        is_mock=False,
                        source_trust="official",
                        error_code="NETWORK_ERROR",
                        error_message="A network error occurred while communicating with TinyFish.",
                    )

            # Loop exited without success (exhausted retries or deadline)
            self.circuit_breaker.record_failure()
            recorded_outcome = True
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(canonical_url, last_error_code.lower()),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=canonical_url,
                title=None,
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_live",
                status="unavailable",
                is_mock=False,
                source_trust="official",
                error_code=last_error_code,
                error_message=last_error_message,
            )

        finally:
            if is_probe and not recorded_outcome:
                self.circuit_breaker.record_probe_abandoned()

    async def retrieve(self, request: DocRetrievalRequest) -> DocRetrievalResponse:
        """Resolve approved documentation target and execute live TinyFish retrieval."""
        res = await resolve_documentation_target_async(
            query=request.query,
            target_url=request.target_url,
            ecosystem=request.ecosystem,
            search_fn=self.search,
        )
        is_valid, target_url, err = res

        if not is_valid or not target_url:
            return DocRetrievalResponse(
                status="rejected",
                provider="tinyfish_live",
                is_mock=False,
                total_results=0,
                evidence=[],
                message=err or "Target URL or query could not be resolved to approved documentation.",
            )

        # Check credentials before making network calls
        if not self.api_key:
            return DocRetrievalResponse(
                status="unavailable",
                provider="tinyfish_live",
                is_mock=False,
                total_results=0,
                evidence=[],
                message="TinyFish API credentials (TINYFISH_API_KEY) are not configured. Run in Mock Mode for offline development.",
            )

        # Execute live fetch
        evidence_item = await self.fetch_url(target_url)
        evidence_list = [evidence_item] if evidence_item.status == "success" else []

        overall_status = evidence_item.status
        msg = "Live official documentation evidence retrieved via TinyFish." if overall_status == "success" else evidence_item.error_message

        return DocRetrievalResponse(
            status=overall_status,
            provider="tinyfish_live",
            is_mock=False,
            total_results=len(evidence_list),
            evidence=evidence_list,
            message=msg,
        )

    async def search(self, query: str, ecosystem: str = "stripe", limit: int = 5) -> DocSearchResponse:
        """Search for candidate documentation pages using TinyFish Search API.

        INVARIANT: Search result snippets are indexing previews only and cannot be used
        as verified evidence of API contract violations. Full official documentation must
        be retrieved via the Fetch API and validated by the QuoteVerifier with SHA-256 hashing.
        """
        if hasattr(query, "query"):
            query_obj = query
            query = query_obj.query
            ecosystem = getattr(query_obj, "ecosystem", ecosystem)
            limit = getattr(query_obj, "limit", limit)

        raw_query = query.strip() if query else ""
        if not raw_query:
            return DocSearchResponse(
                query=query or "",
                ecosystem=ecosystem,
                provider="tinyfish_live",
                is_mock=False,
                status="empty",
                total_results=0,
                results=[],
                error_message="Search query was empty.",
            )

        # Check credentials before making network calls
        if not self.api_key:
            return DocSearchResponse(
                query=raw_query,
                ecosystem=ecosystem,
                provider="tinyfish_live",
                is_mock=False,
                status="unavailable",
                total_results=0,
                results=[],
                error_code="CREDENTIALS_MISSING",
                error_message="TinyFish API credentials (TINYFISH_API_KEY) are not configured. Run in Mock Mode for offline development.",
            )

        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            logger.warning("TinyFish circuit breaker is %s; rejecting search for '%s'", self.circuit_breaker.state, raw_query)
            return DocSearchResponse(
                query=raw_query,
                ecosystem=ecosystem,
                provider="tinyfish_live",
                is_mock=False,
                status="unavailable",
                total_results=0,
                results=[],
                error_code="CIRCUIT_OPEN",
                error_message="TinyFish circuit breaker is OPEN due to repeated transient failures.",
            )

        # Build clean search query for Stripe documentation
        cleaned = raw_query.lower().replace("stripe.", "").replace(".", " ").replace("_", " ")
        tokens = [t for t in cleaned.split() if t not in ("stripe", "python")]
        if not tokens:
            tokens = ["api"]
        search_query = " ".join(tokens)

        # Query parameters per official TinyFish Search API specification
        params = {
            "query": f"stripe {search_query}",
            "include_domains": "docs.stripe.com,stripe.com",
            "location": "US",
            "language": "en",
        }

        # Request headers: Authentication via X-API-Key, NEVER log full credentials
        headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": f"APICompass/{settings.APP_VERSION}",
        }

        start_time = self._time_fn()
        overall_budget = min(10.0, self.timeout)
        max_attempts = 1 + max(0, self.max_retries)
        last_error_code = "NETWORK_ERROR"
        last_error_message = "A network error occurred while communicating with TinyFish search."

        for attempt in range(max_attempts):
            elapsed = self._time_fn() - start_time
            remaining_budget = overall_budget - elapsed
            if remaining_budget <= 0:
                return DocSearchResponse(
                    query=raw_query,
                    ecosystem=ecosystem,
                    provider="tinyfish_live",
                    is_mock=False,
                    status="unavailable",
                    total_results=0,
                    results=[],
                    error_code="TIMEOUT",
                    error_message=f"TinyFish search request timed out after {min(10.0, self.timeout)}s.",
                )

            attempt_timeout = remaining_budget
            timeout = httpx.Timeout(attempt_timeout, connect=min(5.0, attempt_timeout))

            try:
                async with asyncio.timeout(attempt_timeout):
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.get(
                            self.search_base_url,
                            headers=headers,
                            params=params,
                        )

                # Check response size limit (10MB)
                if len(response.content) > 10 * 1024 * 1024:
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="unavailable",
                        total_results=0,
                        results=[],
                        error_code="RESPONSE_TOO_LARGE",
                        error_message="Search response exceeded maximum size limit of 10MB.",
                    )

                # Non-retryable: Auth failure (401, 403)
                if response.status_code in (401, 403):
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="auth_failed",
                        total_results=0,
                        results=[],
                        error_code="AUTHENTICATION_FAILED",
                        error_message="TinyFish authentication failed. Check TINYFISH_API_KEY.",
                    )

                # Rate limiting (429)
                if response.status_code == 429:
                    retry_after_str = response.headers.get("retry-after")
                    backoff, should_abort = self._calculate_backoff(attempt, retry_after_str)
                    if should_abort:
                        return DocSearchResponse(
                            query=raw_query,
                            ecosystem=ecosystem,
                            provider="tinyfish_live",
                            is_mock=False,
                            status="rate_limited",
                            total_results=0,
                            results=[],
                            error_code="RATE_LIMITED",
                            error_message="TinyFish search rate limit reached. Please retry later.",
                        )
                    elapsed_now = self._time_fn() - start_time
                    if attempt < max_attempts - 1 and elapsed_now + backoff < overall_budget and retry_after_str is not None:
                        await self._sleep_fn(backoff)
                        continue
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="rate_limited",
                        total_results=0,
                        results=[],
                        error_code="RATE_LIMITED",
                        error_message="TinyFish search rate limit reached. Please retry later.",
                    )

                # Transient server errors: 502, 503, 504 (Retryable)
                if response.status_code in (502, 503, 504):
                    last_error_code = "PROVIDER_ERROR"
                    last_error_message = f"TinyFish search service returned HTTP {response.status_code}"
                    if attempt < max_attempts - 1:
                        retry_after_str = response.headers.get("retry-after")
                        backoff, should_abort = self._calculate_backoff(attempt, retry_after_str)
                        if should_abort:
                            break
                        elapsed_now = self._time_fn() - start_time
                        if elapsed_now + backoff < overall_budget:
                            await self._sleep_fn(backoff)
                            continue
                        else:
                            last_error_code = "TIMEOUT"
                            last_error_message = f"TinyFish search request timed out after {min(10.0, self.timeout)}s."
                    break

                # Non-retryable provider error (400, 404, 500, etc.)
                if response.status_code != 200:
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="unavailable",
                        total_results=0,
                        results=[],
                        error_code="PROVIDER_ERROR",
                        error_message=f"TinyFish search service returned HTTP {response.status_code}",
                    )

                # Parse JSON
                try:
                    payload = response.json()
                except Exception:
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="unavailable",
                        total_results=0,
                        results=[],
                        error_code="INVALID_RESPONSE_JSON",
                        error_message="Provider response could not be parsed as JSON.",
                    )

                raw_results = payload.get("results")
                if not isinstance(raw_results, list) or len(raw_results) == 0:
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="empty",
                        total_results=0,
                        results=[],
                        error_message="TinyFish search returned zero results.",
                    )

                # Process and rank results
                candidate_items: List[SearchResultItem] = []

                for raw_item in raw_results:
                    if not isinstance(raw_item, dict):
                        continue

                    item_url = raw_item.get("url")
                    if not item_url or not isinstance(item_url, str):
                        continue

                    # Pre-flight SSRF validation: reject suspicious / unapproved domains
                    is_valid, canonical_url, err = validate_destination_url(item_url)
                    if not is_valid:
                        logger.warning("Search result rejected by SSRF filter: %s (%s)", item_url, err)
                        continue

                    title = raw_item.get("title")
                    snippet = raw_item.get("snippet")
                    site_name = raw_item.get("site_name") or raw_item.get("domain") or "docs.stripe.com"
                    raw_pos = raw_item.get("position", 1)
                    try:
                        raw_pos = int(raw_pos)
                    except (ValueError, TypeError):
                        raw_pos = 1

                    # Compute relevance score for candidate ranking
                    # 1. Position weight (1st result gets 0.40, decays to 0.10)
                    pos_score = max(0.10, 0.40 * (1.0 - (min(raw_pos, 10) - 1) / 10.0))

                    # 2. Token match in URL & Title
                    tok_score = 0.0
                    url_lower = canonical_url.lower()
                    title_lower = (title or "").lower()

                    for tok in tokens:
                        if tok in url_lower:
                            tok_score += 0.30
                        if tok in title_lower:
                            tok_score += 0.20

                    # 3. Path bonus for API reference documentation
                    path_bonus = 0.10 if "/api/" in url_lower else 0.0

                    relevance = min(0.99, max(0.05, pos_score + tok_score + path_bonus))

                    candidate_items.append(
                        SearchResultItem(
                            url=item_url,
                            canonical_url=canonical_url,
                            title=title,
                            snippet=snippet,
                            site_name=site_name,
                            position=raw_pos,
                            relevance_score=round(relevance, 2),
                            is_approved_domain=True,
                        )
                    )

                if not candidate_items:
                    return DocSearchResponse(
                        query=raw_query,
                        ecosystem=ecosystem,
                        provider="tinyfish_live",
                        is_mock=False,
                        status="empty",
                        total_results=0,
                        results=[],
                        error_message="Zero search results passed security destination validation.",
                    )

                # Sort descending by relevance_score
                candidate_items.sort(key=lambda x: x.relevance_score, reverse=True)

                # Reassign positions after ranking and clamp to limit
                clamped_limit = min(10, max(1, limit))
                final_results = candidate_items[:clamped_limit]
                for idx, item in enumerate(final_results):
                    item.position = idx + 1

                return DocSearchResponse(
                    query=raw_query,
                    ecosystem=ecosystem,
                    provider="tinyfish_live",
                    is_mock=False,
                    status="success",
                    total_results=len(final_results),
                    results=final_results,
                    error_message=None,
                )

            except (httpx.TimeoutException, TimeoutError):
                last_error_code = "TIMEOUT"
                last_error_message = f"TinyFish search request timed out after {min(10.0, self.timeout)}s."
                if attempt < max_attempts - 1:
                    backoff, should_abort = self._calculate_backoff(attempt)
                    if should_abort:
                        break
                    elapsed_now = self._time_fn() - start_time
                    if elapsed_now + backoff < overall_budget:
                        await self._sleep_fn(backoff)
                        continue
                break

            except (httpx.NetworkError, ConnectionResetError):
                last_error_code = "NETWORK_ERROR"
                last_error_message = "A network error occurred while communicating with TinyFish search."
                if attempt < max_attempts - 1:
                    backoff, should_abort = self._calculate_backoff(attempt)
                    if should_abort:
                        break
                    elapsed_now = self._time_fn() - start_time
                    if elapsed_now + backoff < overall_budget:
                        await self._sleep_fn(backoff)
                        continue
                break

            except Exception:
                return DocSearchResponse(
                    query=raw_query,
                    ecosystem=ecosystem,
                    provider="tinyfish_live",
                    is_mock=False,
                    status="unavailable",
                    total_results=0,
                    results=[],
                    error_code="PROVIDER_ERROR",
                    error_message="An unexpected error occurred while communicating with TinyFish search.",
                )

        return DocSearchResponse(
            query=raw_query,
            ecosystem=ecosystem,
            provider="tinyfish_live",
            is_mock=False,
            status="unavailable",
            total_results=0,
            results=[],
            error_code=last_error_code,
            error_message=last_error_message,
        )

