# APICompass — Evidence Retrieval & Validation Integrity Specification

**Repository**: [https://github.com/shivampathak890/APICompass.git](https://github.com/shivampathak890/APICompass.git)  
**Branch**: `feature/verification-integrity`  
**Date**: October 21, 2026  
**Status**: Authoritative Evidence Integrity Verification & Test Specification  

---

## 1. Overview of Evidence Architecture

APICompass operates on a zero-hallucination evidence model:
> **"The model proposes; deterministic code decides which claims can be displayed as verified."**

Every finding emitted as a verified contract issue must be deterministically backed by an authentic, officially retrieved documentation quote, validated by exact substring matching and cryptographic SHA-256 content hashing.

```
┌─────────────────────────────────┐
│ User Code (Zero Execution AST)  │ ──> AST Candidates (e.g. stripe.Charge.create)
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ SSRF Allowlist & Security Guard │ ──> Whitelisted Hosts: docs.stripe.com, stripe.com, github.com
└────────────────┬────────────────┘     Rejects: HTTP, Private IPs, Metadata endpoints, Lookalikes
                 │
                 ├── [Live Mode: MOCK_MODE=false] ──> TinyFish Live Search & Fetch
                 └── [Offline Mode: MOCK_MODE=true] ──> Quarantined Mock Fixtures
                 │
                 ▼
┌─────────────────────────────────┐
│ Relevance Guard & Disjoint Filter│ ──> Discards cross-resource docs (e.g. Customer docs for Charge)
└────────────────┬────────────────┘     Rejects search snippets; requires full documentation pages
                 │
                 ▼
┌─────────────────────────────────┐
│ Deterministic Contract Matching │ ──> ContractExtractor & ContractComparator
└────────────────┬────────────────┘     Detects: deprecated ops, legacy params, missing required, constraints
                 │
                 ▼
┌─────────────────────────────────┐
│ Exact Quote Verifier & SHA-256  │ ──> Exact byte substring containment in retrieved document
└────────────────┬────────────────┘     Validates cryptographic content hash
                 │
                 ▼
┌─────────────────────────────────┐
│ Mock Quarantine Guard           │ ──> Synthetic mock evidence CANNOT produce verified production verdicts
└────────────────┬────────────────┘     Forces 'mock_quarantined' / 'unable_to_verify'
                 │
                 ▼
┌─────────────────────────────────┐
│ Conservative Adjudication Court │ ──> Final Verdict: CONFIRMED | LIKELY | NEEDS_REVIEW | NOT_SUPPORTED
└─────────────────────────────────┘
```

---

## 2. The 10 Evidence Verification Dimensions

### 1. Evidence Source Identity
- **Requirement**: Every evidence record must explicitly state its provider (`tinyfish_live` vs `tinyfish_mock`), ecosystem (`stripe`), package name (`stripe`), and source trust (`official` vs `mock_fixture` vs `untrusted`).
- **Implementation**: [`NormalizedEvidence`](backend/app/schemas/documentation.py) schema mandates `provider`, `source_trust`, and `ecosystem`. Search snippets without full page context are rejected by `is_evidence_relevant()` (`is_full_page == True` required).

### 2. Source Reference Validity
- **Requirement**: URLs must be canonical, valid HTTPS references to approved documentation domains.
- **Implementation**: [`validate_destination_url()`](backend/app/services/documentation/security.py) validates destination URLs against `APPROVED_CANONICAL_HOSTS` (`docs.stripe.com`, `stripe.com`, `github.com`).
  - Prohibits loopback (`127.0.0.1`), private RFC-1918 ranges, cloud metadata (`169.254.169.254`, `metadata.google.internal`), embedded credentials (`user:pass@`), and non-443 ports.

### 3. Relevance to the Detection Rule
- **Requirement**: Evidence must address the specific API resource and method being analyzed.
- **Implementation**: [`is_evidence_relevant()`](backend/app/services/evidence/adjudicator.py) inspects token overlap and rejects disjoint resources. For example, if analyzing `stripe.Charge.create`, documentation for `Customer`, `Invoice`, or `Subscription` is rejected with an explicit disjoint error.

### 4. Accuracy of Extracted Facts
- **Requirement**: Structured parameters and constraints extracted from documentation must represent actual API behavior, not inferred guesses.
- **Implementation**: [`ContractExtractor`](backend/app/services/evidence/contract_extractor.py) extracts parameters only when grounded in explicit headings or parameter lists. Does not infer missing fields when the documentation does not establish they are required.

### 5. Relationship Between Evidence and Conclusion
- **Requirement**: A finding is asserted only if the matched evidence explicitly demonstrates the violation.
- **Implementation**: [`QuoteVerifier`](backend/app/services/evidence/quote_verifier.py) verifies that the exact sentence or clause claiming deprecation or required status exists word-for-word in the stored document excerpt.

### 6. Handling of Missing Evidence
- **Requirement**: Missing evidence must **never** be treated as proof of a defect.
- **Implementation**: When documentation cannot be retrieved (404, missing URL, or unregistered method), the adjudicator yields `unable_to_verify` with reason `NO_DOCUMENTATION_RETRIEVED`. Zero findings are emitted against user code.

### 7. Handling of Contradictory Evidence
- **Requirement**: When multiple documentation excerpts provide conflicting requirements, the engine must preserve uncertainty.
- **Implementation**: [`ContractMatcher.match_candidate_to_evidence()`](backend/app/services/evidence/contract_matcher.py) compares parameter contracts across multiple retrieved evidence records. If one source marks a parameter required while another marks it deprecated, the matcher sets `is_ambiguous=True` with rationale `"Conflicting documentation detected"` and emits zero findings.

### 8. Handling of Stale Documentation
- **Requirement**: Documentation must record its API version date, and version mismatches must be disclosed.
- **Implementation**: [`NormalizedEvidence.doc_version`](backend/app/schemas/documentation.py) stores the Stripe API version (e.g. `2024-04-10`). The report includes `limitations_and_caveats` disclosing that contract findings apply to the documented version.

### 9. Separation of Original Evidence from AI-Generated Explanations
- **Requirement**: AI model explanations must never masquerade as evidence, and must not override deterministic evidence checks.
- **Implementation**:
  - LLM suggestions are segregated into `report.ai_suggestions` and `report.llm_reasoning_summary`.
  - Findings in `report.verified_issues` require deterministic `QuoteVerifier` approval with exact substring match and SHA-256 hash.
  - Test `test_08_llm_cannot_promote_unsupported_suggestion` verifies that even if an LLM returns a hallucinated finding, the adjudicator discards it.

### 10. Correct Handling of Retrieval Failures
- **Requirement**: External network dropouts, HTTP 429 rate limits, and gateway timeouts must fail safely.
- **Implementation**:
  - `TinyFishLiveRetriever` catches `httpx.TimeoutException` and HTTP 429, recording the failure in [`CircuitBreaker`](backend/app/services/documentation/circuit_breaker.py).
  - Normalizes the failure into `NormalizedEvidence(status="unavailable", source_trust="untrusted", error_code="RATE_LIMITED")`.
  - Adjudicator transitions to `unable_to_verify` with explicit limitation `RETRIEVAL_FAILED`.

---

## 3. Evidence Outcome Classification Taxonomy

To ensure consistent communication across backend services, frontend presentation, and audit logs, APICompass maps technical adjudication states to four standardized outcomes:

| Proposed Classification | APICompass Technical Status | Definition & Invariants | UI Visual Badge |
| :--- | :--- | :--- | :--- |
| **`CONFIRMED`** | `verification_status="verified"`, `verdict="issues_found"` | Evidence satisfies all confirmation requirements: live official documentation, allowlisted domain, exact substring quote match, valid SHA-256 hash, non-ambiguous contract match. | Green `VERIFIED` Badge with direct doc quote and link |
| **`LIKELY`** | `confidence="probable"`, `verification_status="unverified_suggestion"` | Strong supporting evidence or advisory suggestion exists, but exact full-page substring proof or version certainty is incomplete. | Yellow `SUGGESTION` Badge with cautionary advisory notice |
| **`NEEDS_REVIEW`** | `verification_status="unable_to_verify"`, `status="unresolved"` | Evidence is incomplete, ambiguous, contradictory, or quarantined under offline mock rules. Human review required. | Amber `MOCK QUARANTINE` or Gray `UNABLE TO VERIFY` Badge |
| **`NOT_SUPPORTED`** | `is_verified=False`, `match_method="none"`, `findings=[]` | Available documentation contradicts or does not contain the proposed finding. The claim is discarded. | No finding emitted; documented under `unresolved_candidates` |

### Compatibility Mapping

```
                                  EVALUATION OUTCOME
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
   Live Official Evidence?       Conflicting or Missing?      Fabricated / Unrelated?
            │                             │                             │
    Exact Substring Match?                ▼                             ▼
     SHA-256 Provenance?            NEEDS_REVIEW                  NOT_SUPPORTED
            │                   (unable_to_verify)               (Quote Rejected)
     ┌──────┴──────┐            - Mock Quarantine                - Disjoint Resource
     ▼             ▼            - Ambiguous Match                - Missing Substring
 CONFIRMED      LIKELY          - Network Dropout
 (verified)  (suggestion)
```

---

## 4. Automated Evidence Integrity Test Suite

A dedicated regression test suite has been implemented in [`backend/tests/test_evidence_integrity.py`](backend/tests/test_evidence_integrity.py) covering all 7 critical failure and success modes:

| Test Name | Verification Focus | Result |
| :--- | :--- | :--- |
| `test_valid_evidence_satisfies_confirmation_requirements` | Confirms live official Stripe Charge documentation produces `CONFIRMED` (`verified`) status with exact quote substring. | **PASS** |
| `test_missing_evidence_handled_conservatively_never_false_alarm` | Confirms absent documentation yields `NEEDS_REVIEW` (`unable_to_verify`) with zero false findings. | **PASS** |
| `test_irrelevant_evidence_rejected_by_relevance_guard` | Confirms Customer documentation provided for a Charge call is rejected as `NOT_SUPPORTED`. | **PASS** |
| `test_contradictory_evidence_preserves_uncertainty` | Confirms conflicting parameter specifications yield `NEEDS_REVIEW` with `is_ambiguous=True`. | **PASS** |
| `test_invalid_source_references_rejected_by_provenance_guard` | Confirms unapproved hosts, private IPs (SSRF), and metadata URLs are rejected by provenance checks. | **PASS** |
| `test_retrieval_failures_produce_controlled_abstention` | Confirms TinyFish HTTP 429 rate limit produces `unable_to_verify` without crash. | **PASS** |
| `test_unsupported_conclusions_and_fabricated_quotes_rejected` | Confirms hallucinated quotes absent from retrieved docs receive `NOT_SUPPORTED` (`is_verified=False`). | **PASS** |

### Execution Command & Verified Output
```bash
$ PYTHONPATH=backend ./.venv/bin/python -m pytest backend/tests/test_evidence_integrity.py -v
============================== 7 passed in 0.53s ===============================
```

---

## 5. External Retrieval Sources & Provenance Metadata

When APICompass runs in Live Retrieval Mode (`MOCK_MODE=false`), external documentation is ingested through TinyFish APIs:

| Property | Value / Specification |
| :--- | :--- |
| **Search Base URL** | `https://api.search.tinyfish.ai` |
| **Fetch Base URL** | `https://api.fetch.tinyfish.ai` |
| **Permitted Target Hosts** | `stripe.com`, `docs.stripe.com`, `github.com` |
| **Timeout Policy** | `15.0s` connect and read timeout per request |
| **Retry & Backoff** | 2 retries with exponential backoff (`0.05s` base) |
| **Circuit Breaker** | Trips after 3 consecutive failures; 30s recovery cooldown |
| **Stored Metadata** | `source_url`, `canonical_url`, `title`, `retrieved_at` (ISO 8601 UTC), `content_sha256`, `doc_version` |
| **Integrity Invariant** | Full HTML/Markdown page text is hashed with SHA-256 upon receipt. Any tampering invalidates quote verification. |

---

## 6. Gaps Identified & Remaining Risks

1. **Version Drift in Upstream Docs**: Stripe occasionally updates parameter recommendations. When running in offline mock mode, fixtures in `mock_adapter.py` reflect the `2024-04-10` API version contract. In live mode, TinyFish retrieves the active upstream version.
2. **Dynamic Argument Construction**: If Python code constructs parameters dynamically via `dict(**kwargs)` or reads them from external config files, static AST cannot determine the runtime values. APICompass abstains on dynamic arguments by design.
3. **External Provider Availability**: In live mode, TinyFish uptime and Stripe documentation availability directly impact retrieval. The in-memory circuit breaker prevents resource exhaustion during outages, cleanly falling back to `unable_to_verify`.
