# APICompass Fix Proposal Workflow & Safety Specification

This document details the architecture, safety invariants, eligibility policy, re-verification pipeline, and test verification for APICompass's **Evidence-Gated Fix Proposal** feature.

---

## 1. Core Principles & Safety Guarantees

Fix proposals in APICompass exist to assist developers in correcting verified or clearly labeled candidate issues without introducing regressions, speculative changes, or security risks.

### The 10 Invariants:
1. **Evidence-Gated Eligibility**: A fix is proposed only when the finding and the relevant documentation contract are sufficiently established under verified evidence.
2. **Deterministic Contextual Explanation**: Every proposed change explains *why* it addresses the finding with direct citations to official documentation quotes and URLs.
3. **Preservation of Unrelated Logic**: Edits are scoped strictly to the target API call AST node, preserving all surrounding logic, functions, comments, and indentation.
4. **Prohibition on Value Invention**: APICompass **never** invents credentials, API keys, customer identifiers, or arbitrary runtime values (e.g. inserting synthetic monetary amounts like `amount=1000`). If a required parameter cannot be statically derived, APICompass abstains with an explicit notice (`INVENTED_VALUE_PROHIBITED`).
5. **Zero Automatic Code Execution**: Submitted source code and proposed fixes are analyzed solely via static AST inspection (`ast.parse`, `ast.walk`). Code is **never executed, imported, or evaluated at runtime**.
6. **Explicit Proposal Classification**: Proposals are distinctly categorized into:
   - `verified_correction`: Evidence-supported against live official documentation with clean, verified re-verification.
   - `suggested_patch`: Fixes derived from offline mock fixtures, incomplete contracts, or partially resolved re-verifications.
   - `ineligible`: Abstention due to ambiguous evidence, missing contracts, or syntax errors.
7. **In-Memory Static Re-Verification**: The proposed fix is immediately re-analyzed through the server-side static analysis pipeline.
8. **Contract Evidence Re-Check**: The re-verifier re-evaluates the transformed AST against official contract rules.
9. **No "Valid Just Because It Parses" False Equivalence**: Syntactic validity (`ast.parse`) is a minimum precondition, not proof of correctness. An edit that parses but retains the violation, bypasses the API call, or leaves issues unresolved is never marked as `verified_resolved`.
10. **Ambiguity Abstention**: If the documentation contract is ambiguous or conflicting, APICompass explicitly explains why an automatic fix cannot safely be proposed and requires manual review.

---

## 2. End-to-End Workflow

The fix proposal lifecycle follows a 10-step pipeline:

```
[Developer Request]
        │
        ▼
[Step 1: Input Syntax Validation] ────── (Syntax Error) ──► status="syntax_check_failed"
        │                                                    proposal_type="ineligible"
        ▼
[Step 2: Ecosystem Guard] ────────────── (Unsupported) ───► status="insufficient_evidence"
        │
        ▼
[Step 3: Server-Side Adjudication] (Recomputes candidate assessment independently)
        │
        ▼
[Step 4: Candidate Authenticity Check] ─ (Not Found) ────► status="unsupported_candidate"
        │
        ▼
[Step 5: Ambiguity & Mock Quarantine Check]
   ├─ Ambiguous Contract ────────────────────────────────► status="insufficient_evidence"
   │                                                        proposal_type="ineligible"
   │                                                        (Clear explanation of ambiguity)
   └─ Mock Evidence Only ────────────────────────────────► status="mock_evidence_only"
                                                            proposal_type="suggested_patch"
        │
        ▼
[Step 6: Eligibility Policy Evaluation (`policy.py`)]
   ├─ Missing Runtime Parameter ─────────────────────────► status="insufficient_evidence"
   │                                                        warning="INVENTED_VALUE_PROHIBITED"
   └─ Verified / Eligible Issue ─────────────────────────► status="evidence_supported"
        │
        ▼
[Step 7: AST-Preserving Code Transformation]
        │  (Extracts original call slice, maps parameters, generates unified diff)
        ▼
[Step 8: Proposed Code Syntax Check] ─── (Syntax Error) ──► status="syntax_check_failed"
        │                                                    reverification_status="syntax_invalid"
        ▼
[Step 9: In-Memory Pipeline Re-Verification]
   ├─ Original violation persists ───────────────────────► reverification_status="concern_persists"
   ├─ API candidate deleted or bypassed ─────────────────► reverification_status="reverification_inconclusive"
   │                                                        warning="DID_NOT_ADDRESS_FINDING"
   ├─ Unresolved issues remain ──────────────────────────► reverification_status="partially_resolved"
   └─ API candidate resolved clean under live docs ──────► reverification_status="verified_resolved"
        │
        ▼
[Step 10: Response Assembly & Classification]
   ├─ live_official_source + verified_resolved ──────────► proposal_type="verified_correction"
   ├─ mock_fixture or partially_resolved ────────────────► proposal_type="suggested_patch"
   └─ otherwise ─────────────────────────────────────────► proposal_type="ineligible"
```

---

## 3. Eligibility Policy & Ambiguity Handling

Eligibility is governed by [`backend/app/services/fixes/policy.py`](file:///home/shivam-pathak018/Desktop/AZINHACK/backend/app/services/fixes/policy.py):

### Ambiguity Detection:
If `candidate.abstention_reason in ("AMBIGUOUS_OPERATION_MATCH", "CONFLICTING_DOCUMENTATION")` or `candidate.evidence_match.is_ambiguous`:
- Fix generation immediately aborts.
- `status="insufficient_evidence"`, `proposal_type="ineligible"`, `reverification_status="not_attempted"`.
- A human-readable explanation states the conflicting operations and instructs manual developer review.

### Runtime Value Invention Prohibition:
Financial transactions and API calls require domain knowledge. If an issue is classified as `missing_required_parameter`:
- APICompass refuses to guess or invent arbitrary numbers or IDs.
- Eligibility returns `insufficient_evidence` with warning `INVENTED_VALUE_PROHIBITED`.
- Summary and reasoning guide the developer on which exact required parameter needs to be provided.

### Mock Evidence Isolation:
If `evidence_trust == "mock_fixture"` or `is_mock == True`:
- Fix proposals cannot be marked `evidence_supported` or `verified_correction`.
- Status is quarantined to `mock_evidence_only` and `proposal_type="suggested_patch"`.

---

## 4. Re-Verification Pipeline & Verification States

Re-verification in Step 9 executes authoritative server-side static analysis on the modified source string:

| Re-verification Status | Condition | Resulting Proposal Type |
|---|---|---|
| `verified_resolved` | Proposed code parses cleanly, contains an active API candidate, and resolves `clean` against live official documentation. | `verified_correction` |
| `concern_persists` | The proposed code still produces the original verified issue. | `suggested_patch` |
| `partially_resolved` | The original issue was resolved, but other verified issues remain on the candidate. | `suggested_patch` |
| `reverification_inconclusive` | Candidate was bypassed, commented out, or evaluated against mock fixtures. | `suggested_patch` |
| `syntax_invalid` | Proposed code fails `ast.parse`. | `ineligible` |
| `not_attempted` | Fix generation was aborted early due to ambiguity, syntax error, or unknown candidate. | `ineligible` |

---

## 5. Automated Test Coverage

The fix proposal feature is validated by 31 automated tests across two test suites:

### 1. `backend/tests/test_fix_proposal_audit.py` (9 Tests):
1. **`test_01_valid_fix_verified_correction`**: Confirms a valid fix (`source` -> `payment_method` on `Charge.create` -> `PaymentIntent.create`) returns `evidence_supported`, `verified_correction`, and `verified_resolved`.
2. **`test_02_invalid_fix_syntax_regression_rejected`**: Ensures an edit that creates invalid Python syntax is rejected with `syntax_check_failed`, `syntax_invalid`, and `ineligible`.
3. **`test_03_ambiguous_evidence_abstains_with_clear_explanation`**: Verifies that ambiguous operation matches abstain with `insufficient_evidence`, `ineligible`, and explicit explanation.
4. **`test_04_submitted_source_syntax_error_rejected_at_step_one`**: Verifies that malformed user input is immediately rejected before adjudication.
5. **`test_05_edit_leaves_violation_intact_results_in_concern_persists`**: Proves that an ineffective change where the violation remains results in `concern_persists`.
6. **`test_06_edit_bypasses_candidate_results_in_inconclusive`**: Proves that commenting out or bypassing the call is flagged with `reverification_inconclusive` and `DID_NOT_ADDRESS_FINDING`.
7. **`test_07_prohibition_on_inventing_runtime_values`**: Confirms that missing required parameters trigger `INVENTED_VALUE_PROHIBITED` rather than fabricating dummy values.
8. **`test_08_preservation_of_unrelated_logic_and_formatting`**: Ensures unrelated functions, classes, and comments remain byte-for-byte intact.
9. **`test_09_zero_automatic_execution_guarantee`**: Proves that malicious or dangerous code in user source (e.g. `os.system("touch /tmp/pwned")`) is never executed during fix proposal.

### 2. `backend/tests/test_fix_proposals.py` (22 Tests):
Validates candidate lookup, mock quarantine, unapproved URLs, client-supplied trust escalation rejection (422), AST diff bounding, and full-circle live verification.
