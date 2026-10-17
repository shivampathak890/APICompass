"""Deterministic offline mock LLM provider for development and testing."""

from typing import List, Set
from app.services.llm.base import BaseLLMProvider
from app.services.llm.schemas import (
    CandidateReasoning,
    LLMReasoningRequest,
    LLMReasoningResponse,
    ProposedClaim,
)


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock provider that simulates LLM candidate interpretation offline."""

    @property
    def name(self) -> str:
        return "mock"

    async def reason_about_candidates(self, request: LLMReasoningRequest) -> LLMReasoningResponse:
        """Simulate structured candidate reasoning without external network calls."""
        reasonings: List[CandidateReasoning] = []
        suggested_urls: Set[str] = set()

        for cand in request.candidates:
            rec = (cand.receiver or "").lower()
            expr = cand.expression.lower()
            target = cand.target_name.lower()

            if "charge" in rec or "charge" in expr:
                is_source_used = "source=" in request.source.lower() or "source" in expr
                claims: List[ProposedClaim] = []
                uncertainties: List[str] = [
                    "Target Stripe API version in user's environment is unconfirmed.",
                    "Whether merchant account has legacy Charges API permission enabled.",
                ]

                if is_source_used:
                    claims.append(
                        ProposedClaim(
                            claim_type="deprecated_api",
                            affected_candidate_id=cand.candidate_id,
                            description=(
                                "The 'source' token parameter on stripe.Charge.create is legacy. "
                                "Modern Stripe integrations should use the PaymentIntents API."
                            ),
                            referenced_evidence_ids=list(request.existing_evidence_ids),
                            unverified_aspects=(
                                "Requires live official Stripe documentation quote verification "
                                "to confirm parameter deprecation and replacement API."
                            ),
                        )
                    )

                urls = [
                    "https://docs.stripe.com/api/charges/create",
                    "https://docs.stripe.com/api/payment_intents/create",
                ]
                suggested_urls.update(urls)

                reasonings.append(
                    CandidateReasoning(
                        candidate_id=cand.candidate_id,
                        interpretation=(
                            "Invocation of stripe.Charge.create initiates a direct charge. "
                            "Uses the legacy 'source' argument to pass payment credentials."
                            if is_source_used
                            else "Invocation of stripe.Charge.create initiates a direct charge."
                        ),
                        proposed_claims=claims,
                        suggested_documentation_queries=urls,
                        referenced_evidence_ids=list(request.existing_evidence_ids),
                        risk_category="deprecated_api" if is_source_used else "general_guidance",
                        confidence="uncalibrated",
                        uncertainties=uncertainties,
                        reasoning_summary=(
                            "Identified static call to Charge.create with legacy parameter pattern."
                            if is_source_used
                            else "Identified static call to Charge.create."
                        ),
                    )
                )

            elif "paymentintent" in rec or "paymentintent" in expr or "payment_intent" in expr:
                urls = ["https://docs.stripe.com/api/payment_intents/create"]
                suggested_urls.update(urls)
                reasonings.append(
                    CandidateReasoning(
                        candidate_id=cand.candidate_id,
                        interpretation=(
                            "Invocation of stripe.PaymentIntent.create creates a PaymentIntent "
                            "for modern payment processing."
                        ),
                        proposed_claims=[
                            ProposedClaim(
                                claim_type="general_guidance",
                                affected_candidate_id=cand.candidate_id,
                                description=(
                                    "PaymentIntent conforms to current Stripe best practices. "
                                    "Required parameters 'amount' and 'currency' should be verified."
                                ),
                                referenced_evidence_ids=list(request.existing_evidence_ids),
                                unverified_aspects=(
                                    "Parameter completeness requires official Stripe PaymentIntents documentation contract match."
                                ),
                            )
                        ],
                        suggested_documentation_queries=urls,
                        referenced_evidence_ids=list(request.existing_evidence_ids),
                        risk_category="general_guidance",
                        confidence="uncalibrated",
                        uncertainties=["Specific Stripe API version constraints."],
                        reasoning_summary="Modern Stripe payment method call conforming to standard integration patterns.",
                    )
                )
            else:
                urls = ["https://docs.stripe.com/api"]
                suggested_urls.update(urls)
                reasonings.append(
                    CandidateReasoning(
                        candidate_id=cand.candidate_id,
                        interpretation=f"Invocation of '{cand.target_name}' on '{cand.receiver or 'module'}'.",
                        proposed_claims=[
                            ProposedClaim(
                                claim_type="general_guidance",
                                affected_candidate_id=cand.candidate_id,
                                description=(
                                    f"Candidate call '{cand.target_name}' identified. "
                                    "Official contract schema required to evaluate parameters."
                                ),
                                referenced_evidence_ids=[],
                                unverified_aspects="No verified official contract has been confirmed for this operation.",
                            )
                        ],
                        suggested_documentation_queries=urls,
                        referenced_evidence_ids=[],
                        risk_category="general_guidance",
                        confidence="uncalibrated",
                        uncertainties=["Target API endpoint documentation availability."],
                        reasoning_summary=f"Static call identified on {cand.receiver or 'symbol'}.",
                    )
                )

        return LLMReasoningResponse(
            status="mock",
            provider="mock",
            model="mock-reasoning-v1",
            candidate_reasonings=reasonings,
            suggested_documentation_urls=sorted(suggested_urls),
            overall_reasoning_summary=(
                f"Mock LLM reasoning evaluated {len(reasonings)} candidate(s). "
                "All proposed claims remain unverified until corroborated by deterministic Evidence Court."
            ),
            error_message=None,
        )
