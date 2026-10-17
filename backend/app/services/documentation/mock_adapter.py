"""Deterministic offline mock documentation retriever for development and tests.

Returns authentic, official Stripe documentation excerpts clearly tagged as mock fixtures.
Never represents mock fixtures as live data.
"""

from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional

from app.schemas.documentation import (
    DocRetrievalRequest,
    DocRetrievalResponse,
    DocSearchResponse,
    NormalizedEvidence,
    SearchResultItem,
)
from app.services.documentation.base import BaseDocRetriever
from app.services.documentation.normalizer import normalize_documentation_content
from app.services.documentation.registry import (
    resolve_documentation_target,
    resolve_documentation_target_async,
)

# Authentic documentation fixtures extracted from official Stripe resources
# Explicitly tagged and quarantined as offline demonstration fixtures
OFFICIAL_STRIPE_FIXTURES: Dict[str, Dict[str, str]] = {
    "https://docs.stripe.com/api/charges/create": {
        "title": "[Mock Fixture] Create a charge | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "You can use the Charges API to accept payments using Stripe. "
            "However, Stripe now recommends using the Payment Intents API, which provides a unified "
            "integration flow and supports dynamic authentication mechanisms. "
            "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods. "
            "Required parameters: amount (positive integer), currency (three-letter ISO code)."
        ),
    },
    "https://docs.stripe.com/api/charges": {
        "title": "[Mock Fixture] The Charge object | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "The Charge object represents a single payment attempt. "
            "To accept payments, we recommend using the PaymentIntents API instead of the Charges API. "
            "PaymentIntents support strong customer authentication (SCA) and mobile wallets natively."
        ),
    },
    "https://docs.stripe.com/api/payment_intents/create": {
        "title": "[Mock Fixture] Create a PaymentIntent | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "Creates a PaymentIntent object. A PaymentIntent guides you through the process of collecting "
            "a payment from your customer. We recommend using PaymentIntents for all new integrations. "
            "Parameters: amount (integer in cents), currency (three-letter ISO currency code), "
            "automatic_payment_methods (dictionary enabling automated payment method selection)."
        ),
    },
    "https://docs.stripe.com/api/payment_intents": {
        "title": "[Mock Fixture] PaymentIntents | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "A PaymentIntent tracks the lifecycle of a customer payment from creation through payment evaluation "
            "and final settlement. State transitions: requires_payment_method -> requires_confirmation -> succeeded."
        ),
    },
    "https://docs.stripe.com/api/customers/create": {
        "title": "[Mock Fixture] Create a customer | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "Creates a new customer object. You can store customer profiles, payment methods, and contact info. "
            "Parameters: email (string), name (string), description (string), metadata (key-value dictionary)."
        ),
    },
    "https://docs.stripe.com/api/refunds/create": {
        "title": "[Mock Fixture] Create a refund | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "Create a refund for a charge or payment intent. "
            "Parameters: charge (ID of charge to refund), payment_intent (ID of payment intent to refund), "
            "amount (optional partial refund amount in cents)."
        ),
    },
    "https://docs.stripe.com/api/subscriptions/create": {
        "title": "[Mock Fixture] Create a subscription | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "Creates a new subscription on an existing customer. Each customer can have multiple subscriptions. "
            "Parameters: customer (string ID of customer), items (list of subscription items). "
            "Required parameters: customer, items."
        ),
    },
    "https://docs.stripe.com/api/webhook_endpoints/create": {
        "title": "[Mock Fixture] Create a webhook endpoint | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "Creates a new webhook endpoint. Webhook endpoints are notified of events in your Stripe account. "
            "Parameters: url (string URL for endpoint), enabled_events (list of event type strings). "
            "Required parameters: url, enabled_events."
        ),
    },
    "https://docs.stripe.com/api/tokens/create_card": {
        "title": "[Mock Fixture] Create a card token (Deprecated) | Stripe API Reference",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "Creates a single-use token that represents a credit card's details. "
            "This method is deprecated. Stripe recommends using Payment Methods and SetupIntents to safely handle card details. "
            "Parameters: card (dictionary containing number, exp_month, exp_year, cvc)."
        ),
    },
    "https://docs.stripe.com/api": {
        "title": "[Mock Fixture] Stripe API Reference Overview",
        "doc_version": "2024-04-10",
        "demonstration_notice": "Offline test fixture for deterministic evaluation. Not live official documentation.",
        "excerpt": (
            "The Stripe API is organized around REST. Our API has predictable resource-oriented URLs, "
            "accepts form-encoded request bodies, returns JSON-encoded responses, and uses standard HTTP response codes."
        ),
    },
}


def compute_evidence_id(url: str, content: str) -> str:
    """Generate a stable, deterministic evidence identifier."""
    raw = f"{url}:{content}"
    return f"ev_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


class TinyFishMockRetriever(BaseDocRetriever):
    """Deterministic mock retriever for offline testing and local development."""

    def __init__(self) -> None:
        self.fixtures = OFFICIAL_STRIPE_FIXTURES

    async def fetch_url(self, url: str) -> NormalizedEvidence:
        """Return mock evidence for a specific approved URL."""
        # Clean trailing slash for lookup
        clean_url = url.rstrip("/")
        now_utc = datetime.now(timezone.utc).isoformat()

        # Edge case: simulated rate limit
        if "rate_limited" in clean_url:
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(clean_url, "rate_limited"),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=clean_url,
                title="[Mock Fixture] Simulated Rate Limit Exceeded",
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_mock",
                status="unavailable",
                is_mock=True,
                source_trust="mock_fixture",
                doc_version="2024-04-10",
                error_code="RATE_LIMITED",
                error_message="Simulated TinyFish rate limit reached in mock retriever.",
            )

        # Edge case: simulated empty content
        if "empty_content" in clean_url:
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(clean_url, "empty"),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=clean_url,
                title="[Mock Fixture] Empty Documentation Page",
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_mock",
                status="unavailable",
                is_mock=True,
                source_trust="mock_fixture",
                doc_version="2024-04-10",
                error_code="NO_CONTENT_RETURNED",
                error_message="Simulated empty documentation content in mock retriever.",
            )

        # Edge case: simulated malformed content
        if "malformed" in clean_url:
            return NormalizedEvidence(
                evidence_id=compute_evidence_id(clean_url, "malformed"),
                ecosystem="stripe",
                package="stripe",
                source_url=url,
                canonical_url=clean_url,
                title="[Mock Fixture] Malformed Documentation Page",
                content_excerpt="",
                retrieved_at=now_utc,
                provider="tinyfish_mock",
                status="unavailable",
                is_mock=True,
                source_trust="mock_fixture",
                doc_version="2024-04-10",
                error_code="MALFORMED_CONTENT",
                error_message="Simulated malformed content structure in mock retriever.",
            )

        fixture = self.fixtures.get(clean_url) or self.fixtures.get(url) or self.fixtures.get("https://docs.stripe.com/api")
        
        content = fixture["excerpt"]
        title = fixture.get("title")
        if title and not title.startswith("[Mock Fixture]"):
            title = f"[Mock Fixture] {title}"
        doc_version = fixture.get("doc_version", "2024-04-10")

        page_model, cleaned_excerpt = normalize_documentation_content(
            raw_text=content,
            url=url,
            final_url=clean_url,
            title=title,
            doc_version=doc_version,
            provider="tinyfish_mock",
            is_mock=True,
            retrieved_at=now_utc,
        )

        return NormalizedEvidence(
            evidence_id=compute_evidence_id(clean_url, cleaned_excerpt),
            ecosystem="stripe",
            package="stripe",
            source_url=url,
            canonical_url=clean_url,
            title=title,
            content_excerpt=cleaned_excerpt,
            retrieved_at=now_utc,
            provider="tinyfish_mock",
            status="mock",
            is_mock=True,
            source_trust="mock_fixture",
            doc_version=doc_version,
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

    async def retrieve(self, request: DocRetrievalRequest) -> DocRetrievalResponse:
        """Retrieve mock documentation evidence matching query or target URL."""
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
                provider="tinyfish_mock",
                is_mock=True,
                total_results=0,
                evidence=[],
                message=err or "Target URL or query could not be resolved to approved documentation.",
            )

        # Retrieve matching fixture
        evidence_item = await self.fetch_url(target_url)
        
        # Include candidate results if multiple requested
        evidence_list = [evidence_item]
        if request.max_results > 1:
            for cand_url in res.candidate_urls[1:]:
                if cand_url != target_url and len(evidence_list) < request.max_results:
                    cand_ev = await self.fetch_url(cand_url)
                    if cand_ev.status == "mock":
                        evidence_list.append(cand_ev)

            if len(evidence_list) < request.max_results and target_url != "https://docs.stripe.com/api":
                secondary = await self.fetch_url("https://docs.stripe.com/api")
                if secondary.status == "mock":
                    evidence_list.append(secondary)

        # Slice to requested max_results
        result_evidence = evidence_list[:request.max_results]

        return DocRetrievalResponse(
            status="mock",
            provider="tinyfish_mock",
            is_mock=True,
            total_results=len(result_evidence),
            evidence=result_evidence,
            message="Offline mock documentation retrieved successfully from verified demonstration fixtures.",
        )

    async def search(self, query: str, ecosystem: str = "stripe", limit: int = 5) -> DocSearchResponse:
        """Deterministic mock search matching against verified official Stripe fixtures.

        INVARIANT: Mock search results are for ranking and discovery only.
        Snippets are not verified evidence of API contract violations.
        """
        if hasattr(query, "query"):
            query_obj = query
            query = query_obj.query
            ecosystem = getattr(query_obj, "ecosystem", ecosystem)
            limit = getattr(query_obj, "limit", limit)

        raw_query = query.strip()
        if not raw_query:
            return DocSearchResponse(
                query=query,
                ecosystem=ecosystem,
                provider="tinyfish_mock",
                is_mock=True,
                status="empty",
                total_results=0,
                results=[],
                message="Query was empty.",
            )

        # Normalize query tokens (supporting camelCase split, underscore, dot)
        import re
        camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_query)
        cleaned = camel_split.lower().replace("stripe.", "").replace(".", " ").replace("_", " ")
        tokens = [t for t in cleaned.split() if t not in ("stripe", "python")]
        if not tokens:
            tokens = ["api"]

        scored_candidates: List[SearchResultItem] = []

        for fix_url, fix_data in self.fixtures.items():
            url_clean = fix_url.lower().replace("_", "")
            title_lower = (fix_data.get("title") or "").lower()
            excerpt_lower = (fix_data.get("excerpt") or "").lower()

            url_matches = sum(1 for tok in tokens if tok.replace("_", "") in url_clean)
            title_matches = sum(1 for tok in tokens if tok in title_lower)
            excerpt_matches = sum(1 for tok in tokens if tok in excerpt_lower)

            if url_matches == 0 and title_matches == 0 and excerpt_matches == 0:
                continue

            # Prioritize URL path matches heavily over passing excerpt mentions
            raw_score = (url_matches * 5.0) + (title_matches * 2.5) + (excerpt_matches * 0.2)
            if "/api/" in fix_url:
                raw_score += 0.5

            final_score = min(0.99, max(0.10, raw_score / 25.0))
            excerpt_text = fix_data.get("excerpt") or ""
            snippet = excerpt_text[:160] + "..." if len(excerpt_text) > 160 else excerpt_text

            title = fix_data.get("title") or ""
            if not title.startswith("[Mock Fixture]"):
                title = f"[Mock Fixture] {title}"

            scored_candidates.append(
                SearchResultItem(
                    url=fix_url,
                    canonical_url=fix_url,
                    title=title,
                    snippet=snippet,
                    site_name="docs.stripe.com",
                    position=1,  # will be assigned after sort
                    relevance_score=round(final_score, 2),
                    is_approved_domain=True,
                )
            )

        if not scored_candidates:
            # Fallback to general API doc if query looks like stripe
            if "stripe" in raw_query.lower() or "api" in raw_query.lower():
                base_fixture = self.fixtures.get("https://docs.stripe.com/api", {})
                fallback_title = base_fixture.get("title", "Stripe API Reference Overview")
                if not fallback_title.startswith("[Mock Fixture]"):
                    fallback_title = f"[Mock Fixture] {fallback_title}"
                scored_candidates.append(
                    SearchResultItem(
                        url="https://docs.stripe.com/api",
                        canonical_url="https://docs.stripe.com/api",
                        title=fallback_title,
                        snippet=base_fixture.get("excerpt", "")[:160] + "...",
                        site_name="docs.stripe.com",
                        position=1,
                        relevance_score=0.40,
                        is_approved_domain=True,
                    )
                )

        if not scored_candidates:
            return DocSearchResponse(
                query=query,
                ecosystem=ecosystem,
                provider="tinyfish_mock",
                is_mock=True,
                status="empty",
                total_results=0,
                results=[],
                message=f"No mock documentation fixtures matched query '{query}'.",
            )

        # Sort by relevance score descending, tie-breaking by URL for strict determinism
        scored_candidates.sort(key=lambda item: (-item.relevance_score, item.url))

        # Clamp to limit and assign 1-indexed ranks
        clamped_limit = min(10, max(1, limit))
        results = scored_candidates[:clamped_limit]
        for idx, item in enumerate(results):
            item.position = idx + 1

        return DocSearchResponse(
            query=query,
            ecosystem=ecosystem,
            provider="tinyfish_mock",
            is_mock=True,
            status="success",
            total_results=len(results),
            results=results,
            message="Mock documentation search completed successfully (Offline Demonstration Fixtures).",
        )

