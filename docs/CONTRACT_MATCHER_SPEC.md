# APICompass Contract Matcher Specification & Limitations

## 1. Overview and Purpose

The **Contract Matcher** correlates static Python AST call candidates with retrieved official documentation evidence to identify potential API contract violations.

In alignment with APICompass's core architectural principle—**"The model proposes; deterministic code decides"**—the matcher supports only checks that can be strictly justified by available official documentation contracts:
1. An explicitly documented required parameter is missing.
2. A supplied parameter is explicitly documented as unsupported for the relevant operation or SDK version.
3. An operation is explicitly documented as deprecated.
4. A supplied parameter is documented as legacy or deprecated.
5. A supplied value contradicts a clearly documented constraint, when that value can be determined statically.

---

## 2. Architecture: Separation of Concerns

Contract matching is decoupled into three distinct stages:

```
+--------------------------------+
|  NormalizedEvidence (Docs)     |
+---------------+----------------+
                |
                v
+--------------------------------+
|      ContractExtractor         |  <-- Stage 1: Documentation Extraction
| - required / optional params   |
| - deprecation notices          |
| - static value constraints     |
| - version & completeness context
+---------------+----------------+
                |
                v  ExtractedContract
+--------------------------------+
|      ContractComparator        |  <-- Stage 2: Contract Comparison
| - compares AST call arguments  |
| - checks static constraints    |
| - attaches evidence & version  |
+---------------+----------------+
                |
                v  List[ContractFindingCandidate]
+--------------------------------+
|      EvidenceAdjudicator       |  <-- Stage 3: Trust & Quote Verification
| - SHA-256 quote verification   |
| - mock fixture quarantine      |
| - promotes to VerifiedIssue    |
+--------------------------------+
```

### Stage 1: Contract Extraction (`ContractExtractor`)
[`backend/app/services/evidence/contract_extractor.py`](file:///home/shivam-pathak018/Desktop/AZINHACK/backend/app/services/evidence/contract_extractor.py)
- Parses normalized technical documentation into a structured `ExtractedContract`.
- Populates explicit dictionaries for:
  - `required_parameters`: Parameters with `is_required=True` (e.g. `amount`, `currency`).
  - `optional_parameters`: Parameters documented as optional (e.g. `customer`, `description`).
  - `all_parameters`: Complete parameter index, including deprecation and unsupported status.
- Preserves `doc_version` (e.g., `2024-04-10`) and SDK version context.
- Classifies contract completeness:
  - `complete_contract`: Full parameter contract with explicit required-field specifications.
  - `excerpt_only`: Partial narrative summary without exhaustive parameter specifications.

### Stage 2: Contract Comparison (`ContractComparator`)
[`backend/app/services/evidence/contract_comparator.py`](file:///home/shivam-pathak018/Desktop/AZINHACK/backend/app/services/evidence/contract_comparator.py)
- Evaluates AST candidate arguments against the `ExtractedContract`.
- Emits structured `ContractFindingCandidate` findings rather than final verified findings.
- Attaches the source evidence (`finding.evidence = evidence`, `supporting_evidence_id`, `source_url`, `contract_quote`, `contract_version`).

### Stage 3: Evidence Adjudication & Quote Verification (`EvidenceAdjudicator`)
[`backend/app/services/evidence/adjudicator.py`](file:///home/shivam-pathak018/Desktop/AZINHACK/backend/app/services/evidence/adjudicator.py)
- Verifies every finding's supporting quote against the source document using cryptographic SHA-256 hashing.
- Enforces strict mock fixture quarantine: offline mock fixtures can never produce a production `clean` or `issues_found` verdict.
- Only promotes candidate findings to `VerifiedIssue`s when substantiated by live official documentation.

---

## 3. Supported Rules & Guardrails

| Check | Positive Condition | Guardrail / Negative Condition |
| :--- | :--- | :--- |
| **Missing Required Parameter** | Document explicitly states parameter is required AND completeness is `complete_contract` AND field is omitted. | Never inferred if parameter is optional or if document is only an `excerpt_only`. |
| **Unsupported Parameter** | Parameter is explicitly documented as unsupported for the operation/version. | Unknown parameters are never called invalid merely because they were absent from an incomplete excerpt. |
| **Deprecated Operation** | Entire operation/endpoint is explicitly documented as deprecated. | Only flagged when explicit deprecation sentence exists in official documentation. |
| **Legacy / Deprecated Parameter** | Supplied parameter is explicitly documented as legacy/deprecated (e.g. `source` on `stripe.Charge.create`). | Does not flag standard modern parameters. |
| **Static Value Constraint** | Statically known compile-time literal (`is_literal=True`) contradicts documented constraint (e.g. `amount = -50` or `amount = 0`). | Unknown runtime expressions, function calls, and variable identifiers (`is_literal=False`) are never flagged. |

---

## 4. Statically Known Values vs. Unknown Runtime Values

APICompass enforces a strict distinction between statically knowable constants and dynamic runtime expressions:

```python
# Case 1: Statically Known Literal Violation -> FLAGGED
stripe.Charge.create(amount=-50, currency="usd")
# Violation: 'amount' literal value -50 violates documented constraint: must be a positive integer (> 0).

# Case 2: Unknown Dynamic Variable -> HONESTLY PRESERVED (NOT FLAGGED)
stripe.Charge.create(amount=order_total, currency=get_currency())
# 'order_total' is an identifier; 'get_currency()' is a call expression.
# Static analysis cannot determine runtime values; zero false alarms are raised.
```

---

## 5. Candidate Finding Schema

Candidate findings emitted by the matcher conform to `ContractFindingCandidate`:

```json
{
  "finding_id": "iss_cand_001_missing_amount",
  "candidate_id": "cand_001",
  "source_location": { "lineno": 10, "col_offset": 0 },
  "claim_checked": "Required parameters on stripe.Charge.create",
  "violation_type": "missing_required_parameter",
  "explanation": "Missing required 'amount' parameter in stripe.Charge.create call.",
  "parameter_name": "amount",
  "supplied_value_repr": null,
  "is_statically_determined": true,
  "supporting_evidence_id": "ev_stripe_charges_live",
  "source_url": "https://docs.stripe.com/api/charges/create",
  "contract_quote": "Required parameters: amount (positive integer), currency (three-letter ISO code).",
  "match_method": "exact",
  "contract_version": "2024-04-10",
  "limitations": "Applies to direct stripe.Charge.create calls as documented in official API reference."
}
```

---

## 6. Clear Description of Limitations

While the contract matcher provides high precision and zero-execution safety, users and integrating systems should be aware of the following known boundaries:

1. **Static Value Resolution Limits**:
   - The matcher only inspects compile-time literals (`ast.Constant`).
   - Dynamic calculations, values retrieved from configuration files, database queries, or external variables cannot be evaluated at static analysis time.
   - The matcher deliberately abstains from guessing runtime values.

2. **Documentation Scope & Excerpt Incompleteness**:
   - When retrieved documentation is an excerpt or preview (`completeness == "excerpt_only"`), the matcher deliberately disables missing required field checks and unsupported parameter checks to prevent false accusations.
   - Full parameter validation requires fetching complete API reference pages.

3. **Multi-Step State & Precondition Constraints**:
   - The matcher checks per-call parameter contracts (stateless comparison).
   - It cannot verify multi-step business logic (such as whether a webhook was received before capturing a charge, or whether a customer has an attached payment source before creating an invoice).

4. **Third-Party Monkey-Patching & Dynamic Dispatch**:
   - If user code overrides SDK methods at runtime (`stripe.Charge.create = custom_func`), static AST analysis will evaluate the invocation against standard documentation rather than the patched runtime implementation.

5. **Version Divergence**:
   - If the user's project dependencies use an older Stripe SDK version (e.g. `stripe-python 2.x`), but documentation retrieval resolves modern API documentation (`2024-04-10`), version differences may apply. Version context is recorded in findings to assist manual inspection.

---

## 7. Verification Summary

- **Contract Matcher Test Suite**: 13/13 passing tests in [`backend/tests/test_contract_matcher.py`](file:///home/shivam-pathak018/Desktop/AZINHACK/backend/tests/test_contract_matcher.py).
- **Full Backend Regression Suite**: 487/487 passing tests (`pytest -m "not live_smoke"`).
- **Frontend Build**: Clean compile with 0 errors (`npm run build`).

