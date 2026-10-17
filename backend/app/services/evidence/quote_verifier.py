"""Deterministic quotation verification engine.

Performs strict, deterministic substring matching against stored official documentation.
Calculates SHA-256 content hashes, enforces provenance, and guarantees:
- The model proposes; deterministic code decides.
- Never silently rewrites quotations.
- Never uses fuzzy similarity as proof of quotation existence.
- Distinguishes exact matches from whitespace-normalized matches.
"""

import hashlib
import re
from typing import Optional

from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import QuoteKindType, QuoteVerificationResult
from app.services.documentation.security import APPROVED_CANONICAL_HOSTS, validate_destination_url


def compute_content_sha256(text: str) -> str:
    """Compute deterministic SHA-256 hash of documentation text."""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_whitespace(text: str) -> str:
    """Normalize consecutive whitespace characters to a single space and strip edges."""
    if not text:
        return ""
    return " ".join(text.split())


class QuoteVerifier:
    """Deterministic verifier for proposed quotations against official documentation evidence.
    
    Guarantees:
    - Never presents synthetic mock text as an official quotation.
    - Distinguishes exact quotations from paraphrases.
    - Rejects quotes from untrusted, unapproved, or failed evidence sources.
    - Matches deterministically with exact substring or whitespace-normalization only.
    """

    @staticmethod
    def verify_quote(
        proposed_quote: str,
        evidence: NormalizedEvidence,
        expected_url: Optional[str] = None,
        allow_whitespace_normalization: bool = True,
        claimed_quote_kind: QuoteKindType = "exact_quotation",
        require_official: bool = False,
    ) -> QuoteVerificationResult:
        """Verify whether a proposed quotation deterministically exists in the retrieved evidence.

        Args:
            proposed_quote: The alleged quotation text to verify.
            evidence: The NormalizedEvidence record claimed to contain the quote.
            expected_url: Optional check ensuring the quote is attributed to the right URL.
            allow_whitespace_normalization: Whether to permit whitespace-normalized matches.
            claimed_quote_kind: Classification claimed by the caller ('exact_quotation', 'paraphrase', 'structured_contract').
            require_official: If True, synthetic mock evidence will be rejected even if text matches.

        Returns:
            QuoteVerificationResult detailing verification status, match method, quote kind, and content hash.
        """
        content = evidence.content_excerpt or ""
        content_hash = compute_content_sha256(content)
        is_mock = bool(
            evidence.is_mock
            or evidence.provider == "tinyfish_mock"
            or evidence.source_trust == "mock_fixture"
        )

        # 1. Reject empty or whitespace-only quotations
        if not proposed_quote or not proposed_quote.strip():
            return QuoteVerificationResult(
                is_verified=False,
                match_method="none",
                matched_text=None,
                evidence_id=evidence.evidence_id,
                source_url=evidence.canonical_url,
                content_hash=content_hash,
                quote_kind="none",
                is_mock=is_mock,
                error_message="Proposed quotation is empty or whitespace-only.",
            )

        # 2. Mock Quarantine check for official citations
        if require_official and is_mock:
            return QuoteVerificationResult(
                is_verified=False,
                match_method="none",
                matched_text=None,
                evidence_id=evidence.evidence_id,
                source_url=evidence.canonical_url,
                content_hash=content_hash,
                quote_kind="none",
                is_mock=True,
                error_message="Synthetic mock text cannot be presented as an official quotation.",
            )

        # 3. Provenance Validation: Ensure evidence source URL is approved and valid
        is_valid, canonical, err = validate_destination_url(evidence.canonical_url)
        if not is_valid:
            return QuoteVerificationResult(
                is_verified=False,
                match_method="none",
                matched_text=None,
                evidence_id=evidence.evidence_id,
                source_url=evidence.canonical_url,
                content_hash=content_hash,
                quote_kind="none",
                is_mock=is_mock,
                error_message=f"Evidence provenance failure: Source URL is unapproved or invalid ({err}).",
            )

        if evidence.source_trust in ("untrusted", "rejected") or evidence.status in ("unavailable", "rejected", "failed", "rate_limited"):
            return QuoteVerificationResult(
                is_verified=False,
                match_method="none",
                matched_text=None,
                evidence_id=evidence.evidence_id,
                source_url=evidence.canonical_url,
                content_hash=content_hash,
                quote_kind="none",
                is_mock=is_mock,
                error_message=f"Evidence provenance failure: Evidence status is '{evidence.status}' with trust '{evidence.source_trust}'.",
            )

        # 4. Source Attribution Check: Ensure quotation is not attributed to the wrong source
        if expected_url:
            norm_expected = expected_url.rstrip("/")
            norm_canonical = evidence.canonical_url.rstrip("/")
            if norm_expected != norm_canonical:
                return QuoteVerificationResult(
                    is_verified=False,
                    match_method="none",
                    matched_text=None,
                    evidence_id=evidence.evidence_id,
                    source_url=evidence.canonical_url,
                    content_hash=content_hash,
                    quote_kind="none",
                    is_mock=is_mock,
                    error_message=(
                        f"Source attribution mismatch: quote claimed from '{expected_url}', "
                        f"but evidence is from '{evidence.canonical_url}'."
                    ),
                )

        # 5. Paraphrase Claim Rejection: If caller admits this is a paraphrase, do not certify as exact quote
        if claimed_quote_kind == "paraphrase":
            return QuoteVerificationResult(
                is_verified=False,
                match_method="none",
                matched_text=None,
                evidence_id=evidence.evidence_id,
                source_url=evidence.canonical_url,
                content_hash=content_hash,
                quote_kind="paraphrase",
                is_mock=is_mock,
                error_message="Quotation is a paraphrase and cannot substantiate an exact quotation claim.",
            )

        # 6. Exact Substring Verification
        if proposed_quote in content:
            return QuoteVerificationResult(
                is_verified=True,
                match_method="exact",
                matched_text=proposed_quote,
                evidence_id=evidence.evidence_id,
                source_url=evidence.canonical_url,
                content_hash=content_hash,
                quote_kind="exact_quotation",
                is_mock=is_mock,
                error_message=None,
            )

        # 7. Whitespace-Normalized Verification (if enabled)
        if allow_whitespace_normalization:
            norm_quote = normalize_whitespace(proposed_quote)
            norm_content = normalize_whitespace(content)

            if norm_quote in norm_content:
                return QuoteVerificationResult(
                    is_verified=True,
                    match_method="whitespace_normalized",
                    matched_text=norm_quote,
                    evidence_id=evidence.evidence_id,
                    source_url=evidence.canonical_url,
                    content_hash=content_hash,
                    quote_kind="exact_quotation",
                    is_mock=is_mock,
                    error_message=None,
                )

        # 8. Paraphrase Detection: Distinguish paraphrase from completely missing quote
        words = re.findall(r"\b[a-zA-Z_]{3,}\b", proposed_quote.lower())
        if len(words) >= 3:
            content_words = set(re.findall(r"\b[a-zA-Z_]{3,}\b", content.lower()))
            overlap = sum(1 for w in words if w in content_words)
            if (overlap / len(words)) >= 0.5:
                return QuoteVerificationResult(
                    is_verified=False,
                    match_method="none",
                    matched_text=None,
                    evidence_id=evidence.evidence_id,
                    source_url=evidence.canonical_url,
                    content_hash=content_hash,
                    quote_kind="paraphrase",
                    is_mock=is_mock,
                    error_message=(
                        "Quotation appears to be a paraphrase rather than an exact quotation. "
                        "Exact verbatim match is required for verified issues."
                    ),
                )

        # 9. Verification Failure: Quote not present in source text
        return QuoteVerificationResult(
            is_verified=False,
            match_method="none",
            matched_text=None,
            evidence_id=evidence.evidence_id,
            source_url=evidence.canonical_url,
            content_hash=content_hash,
            quote_kind="none",
            is_mock=is_mock,
            error_message="Quotation not found in official documentation excerpt.",
        )

    @classmethod
    def verify_official_quote(
        cls,
        proposed_quote: str,
        evidence: NormalizedEvidence,
        expected_url: Optional[str] = None,
        allow_whitespace_normalization: bool = True,
    ) -> QuoteVerificationResult:
        """Verify an official quotation, rejecting synthetic mock evidence."""
        return cls.verify_quote(
            proposed_quote=proposed_quote,
            evidence=evidence,
            expected_url=expected_url,
            allow_whitespace_normalization=allow_whitespace_normalization,
            claimed_quote_kind="exact_quotation",
            require_official=True,
        )


quote_verifier = QuoteVerifier()
