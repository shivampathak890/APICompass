# APICompass Curated Evaluation & Benchmark Report (v3)

## 1. Executive Summary

This report delivers a rigorous empirical evaluation of **APICompass v3**, assessing the correctness, reliability, and precision of its static Python API-contract analysis, documentation evidence retrieval, and adjudication engine.

The evaluation was conducted using a curated, deterministic benchmark of **26 representative Python test cases** covering real-world Stripe API integration patterns, contract violations, dynamic code constructs, and boundary failure modes.

The evaluation strictly isolates four architectural subsystems:
1. **Python AST Detection & Normalization**: Accurate identification of API operations, receiver symbols, aliases, unpacking, comments, and strings.
2. **Documentation Retrieval Quality**: Real-time or fixture-backed documentation resolution with domain validation, error surfacing, and rate-limit transparency.
3. **Evidence Matching & Quoting**: Deterministic contract comparison against extracted schemas, hash-verified verbatim quotations, and mock quarantine enforcement.
4. **Final Adjudication**: Precedence-based decision rules (`syntax_error` $\to$ `issues_found` $\to$ `unable_to_verify` $\to$ `clean`).

---

## 2. Evaluation Set Composition ($N = 26$)

Every test case in the benchmark is grounded in official Stripe REST API specifications (`https://docs.stripe.com/api/...`), official Python SDK conventions (`stripe-python`), or authoritative contract schemas.

| Category | Cases | Description & Grounding |
| :--- | :--- | :--- |
| **Correct Stripe API Usage** | `EVAL-01`, `EVAL-06`, `EVAL-13`, `EVAL-16`, `EVAL-18` | Compliant calls (`PaymentIntent.create`, `Customer.create`, `StripeClient.v1.charges.create`, direct symbol imports, runtime variables with required params present). |
| **Missing Required Parameters** | `EVAL-02` | `stripe.Charge.create(amount=2000)` missing mandatory `currency`. |
| **Unsupported Parameter Names** | `EVAL-03` | `stripe.Charge.create` with invalid parameter `destination_account`. |
| **Deprecated API Operations** | `EVAL-04` | Legacy `stripe.Token.create(card={...})` where card tokens are deprecated in favor of PaymentMethods. |
| **Constraint & Type Violations** | `EVAL-05`, `EVAL-19` | `amount=-500` (violates positive integer requirement); `amount="twenty"` (string literal passed to integer constraint). |
| **Multi-Call Files (Clean)** | `EVAL-20` | Multiple distinct Stripe calls in one file (`Customer.create` and `PaymentIntent.create`), both fully compliant. |
| **Multi-Call Files (Mixed)** | `EVAL-21` | Multiple distinct Stripe calls where one is valid (`Customer.create`) and one has a violation (`Charge.create` missing `currency`). |
| **Aliased Imports** | `EVAL-22` | `import stripe as st; st.PaymentIntent.create(...)` correctly resolved to canonical `stripe.PaymentIntent.create`. |
| **Comments & Strings Immunity** | `EVAL-23` | Python file containing `# stripe.Charge.create(amount=100)` in comments and docstrings with zero AST call nodes. |
| **Reassigned Variable / Client** | `EVAL-24` | Variable reassignment (`client = stripe.StripeClient; alias = client; alias.v1.charges.create(...)`). |
| **Dynamic `**kwargs` Unpacking** | `EVAL-25` | `stripe.Charge.create(amount=2000, **options)` where parameters are unpacked dynamically at runtime. |
| **Statically Indeterminate Receiver**| `EVAL-26` | Indeterminate factory method call `get_client().create(...)` where receiver binding is dynamically resolved. |
| **Abstention & Edge Cases** | `EVAL-07`, `EVAL-08`, `EVAL-09`, `EVAL-10`, `EVAL-11`, `EVAL-12`, `EVAL-17` | Unsupported operations, non-API functions (`db.create`), unparseable syntax, irrelevant documentation, conflicting documentation, upstream 429 rate limit, and mock evidence quarantine. |
| **Fix Proposal & Quotation Safety** | `EVAL-14`, `EVAL-15` | Syntax regression rejection in proposed fix; rejection of fabricated documentation quotes. |

---

## 3. Subsystem Separation & Analysis

To prevent conflating retrieval errors with static analysis or adjudication bugs, each subsystem was measured independently:

```
+---------------------------------------------------------------------------------------------------------+
|                                        EVALUATION PIPELINE & SUBSYSTEMS                                 |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         | Subsystem 1: AST Detection & Extraction               |
                         | - Accuracy: 100% (26/26)                              |
                         | - Reassigned clients, aliased imports, **kwargs       |
                         | - Comment/string immunity (zero false AST candidates) |
                         +-------------------------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         | Subsystem 2: Documentation Retrieval & Security       |
                         | - Domain allowlist verification (docs.stripe.com)     |
                         | - Honest upstream failure surfacing (EVAL-12: 429)    |
                         | - Mock quarantine invariant enforcement (EVAL-17)     |
                         +-------------------------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         | Subsystem 3: Evidence Matching & Quote Verifier       |
                         | - Verbatim substring & token hash matching (100%)     |
                         | - Irrelevant doc rejection (EVAL-10: 100%)            |
                         | - Contradictory evidence detection (EVAL-11: 100%)    |
                         +-------------------------------------------------------+
                                                     |
                                                     v
                         +-------------------------------------------------------+
                         | Subsystem 4: Final Adjudication & Precedence Engine   |
                         | - Syntax Error Precedence (EVAL-09)                   |
                         | - Multi-call aggregation (EVAL-20, EVAL-21)           |
                         | - Honest abstention on indeterminate ASTs (EVAL-26)   |
                         +-------------------------------------------------------+
```

---

## 4. Benchmark Metrics: Baseline vs. Final

### 4.1 Comparative Confusion Matrix (Defect-Evaluable Cases, $N = 17$)
*Note: Excludes the 9 intentional abstention cases (`EVAL-07`, `EVAL-08`, `EVAL-09`, `EVAL-10`, `EVAL-11`, `EVAL-12`, `EVAL-17`, `EVAL-23`, `EVAL-26`) which are evaluated under the Abstention Integrity metric.*

| Metric | Baseline (Pre-Fix) | Final (Post-Fix) | Delta |
| :--- | :---: | :---: | :---: |
| **True Positives (TP)** | 6 | **7** | +1 |
| **False Positives (FP)** | 1 | **0** | -1 (100% elimination) |
| **True Negatives (TN)** | 9 | **10** | +1 |
| **False Negatives (FN)** | 1 | **0** | -1 (100% elimination) |
| **Precision** | 85.7% (6/7) | **100.0%** (7/7) | **+14.3%** |
| **Recall** | 85.7% (6/7) | **100.0%** (7/7) | **+14.3%** |
| **F1 Score** | 85.7% | **100.0%** | **+14.3%** |
| **Honest Abstentions** | 9 / 9 (100%) | **9 / 9 (100%)** | 0 |
| **Evidence Attribution Accuracy** | 100.0% | **100.0%** | 0 |
| **Repeatability (3 runs)** | 100.0% | **100.0%** | Zero variance |

---

## 5. Defect Analysis & Targeted Resolutions

During baseline measurement of the expanded dataset, two defects were discovered and addressed:

### Defect 1: False Positive on Dynamic `**kwargs` (`EVAL-25`)
- **Observed Behavior**: `stripe.Charge.create(amount=2000, **options)` triggered a False Positive `missing_required_parameter` for `currency`.
- **Root Cause**: The AST analyzer correctly parsed `options` as an unpack node (`value_type="kwargs_unpack"`), but `ContractComparator` simply verified `if req_name not in supplied_kwargs:` without checking whether dynamic keyword arguments were passed.
- **Resolution**: In [`backend/app/services/evidence/contract_comparator.py`](file:///home/shivam-pathak018/Desktop/AZINHACK/backend/app/services/evidence/contract_comparator.py), added `has_kwargs_unpack = any(a.value_type == "kwargs_unpack" for a in ast_call.arguments)`. The missing parameter check is now skipped if `has_kwargs_unpack` is true, recognizing that required arguments may be unpacked at runtime.
- **Outcome**: `EVAL-25` now safely reports `no_issue_detected` / `clean` without false alarms.

### Defect 2: False Negative on Incorrect Parameter Type (`EVAL-19`)
- **Observed Behavior**: `stripe.Charge.create(amount="twenty", currency="usd")` passed without error, producing a False Negative.
- **Root Cause**: The constraint check for `positive_integer` only tested:
  ```python
  if isinstance(val, (int, float)) and val <= 0:
      findings.append(...)
  ```
  If `val` was a string literal (`"twenty"`) or boolean (`True`), the check was bypassed entirely, allowing non-numeric and boolean types to evade detection.
- **Resolution**: Strengthened type validation in `ContractComparator`:
  ```python
  if isinstance(val, bool) or not isinstance(val, (int, float)):
      findings.append(...)
  ```
  Explicit documentation quote citation is preserved from the parameter specification.
- **Outcome**: `EVAL-19` deterministically flags `constraint_violation` with verified evidence.

---

## 6. Complete 26-Case Performance Matrix

| Case ID | Category | Virtual File | Ground Truth | Final Verdict | Status | Latency | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **EVAL-01** | Correct Stripe Usage | `checkout.py` | Negative | `clean` | `no_issue_detected` | 2.1 ms | **PASS** |
| **EVAL-02** | Missing Required Parameter | `charge_missing_currency.py` | Positive | `issues_found` | `verified` | 7.8 ms | **PASS** |
| **EVAL-03** | Unsupported Parameter | `charge_unsupported_destination.py` | Positive | `issues_found` | `verified` | 6.5 ms | **PASS** |
| **EVAL-04** | Deprecated Operation | `deprecated_token_card.py` | Positive | `issues_found` | `verified` | 8.2 ms | **PASS** |
| **EVAL-05** | Constraint Violation (Negative) | `invalid_negative_amount.py` | Positive | `issues_found` | `verified` | 7.1 ms | **PASS** |
| **EVAL-06** | Dynamic Variable | `dynamic_order.py` | Negative | `clean` | `no_issue_detected` | 3.4 ms | **PASS** |
| **EVAL-07** | Unsupported Operation | `unsupported_op.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 2.8 ms | **PASS** |
| **EVAL-08** | Non-API Function (`db.create`) | `database_helper.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 1.9 ms | **PASS** |
| **EVAL-09** | Invalid Python Syntax | `broken_syntax.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 0.9 ms | **PASS** |
| **EVAL-10** | Irrelevant Documentation | `charge_with_customer_docs.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 4.6 ms | **PASS** |
| **EVAL-11** | Ambiguous Documentation | `conflicting_capture.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 22.9 ms | **PASS** |
| **EVAL-12** | Retrieval Failure (Rate Limit) | `refund_outage.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 3.1 ms | **PASS** |
| **EVAL-13** | Valid Call (Customer) | `customer_compliant.py` | Negative | `clean` | `no_issue_detected` | 4.2 ms | **PASS** |
| **EVAL-14** | Fix Proposal Syntax Regression | `fix_syntax_regression.py` | Issue Caught | `issues_found` | `unable_to_verify` | 14.8 ms | **PASS** |
| **EVAL-15** | Unsupported Quote Rejection | `unsupported_claim.py` | Negative | `clean` | `no_issue_detected` | 5.3 ms | **PASS** |
| **EVAL-16** | Modern `StripeClient` Usage | `modern_client.py` | Negative | `clean` | `no_issue_detected` | 4.7 ms | **PASS** |
| **EVAL-17** | Mock Evidence Quarantine | `mock_quarantine.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 2.5 ms | **PASS** |
| **EVAL-18** | Direct Symbol Import | `direct_import.py` | Negative | `clean` | `no_issue_detected` | 3.9 ms | **PASS** |
| **EVAL-19** | Incorrect Parameter Type | `charge_string_amount.py` | Positive | `issues_found` | `verified` | 6.8 ms | **PASS** |
| **EVAL-20** | Multi-Call File (All Clean) | `multiple_clean.py` | Negative | `clean` | `no_issue_detected` | 8.4 ms | **PASS** |
| **EVAL-21** | Multi-Call File (Mixed) | `multiple_mixed.py` | Positive | `issues_found` | `verified` | 9.1 ms | **PASS** |
| **EVAL-22** | Aliased Import (`st.PaymentIntent`) | `aliased_import.py` | Negative | `clean` | `no_issue_detected` | 3.2 ms | **PASS** |
| **EVAL-23** | Comments & String Immunity | `comment_code.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 1.1 ms | **PASS** |
| **EVAL-24** | Reassigned Client Variable | `reassigned_client.py` | Negative | `clean` | `no_issue_detected` | 4.5 ms | **PASS** |
| **EVAL-25** | Dynamic `**kwargs` Unpacking | `kwargs_unpacking.py` | Negative | `clean` | `no_issue_detected` | 3.7 ms | **PASS** |
| **EVAL-26** | Indeterminate Receiver Factory | `dynamic_receiver.py` | Abstention | `unable_to_verify` | `unable_to_verify` | 1.8 ms | **PASS** |

---

## 7. Known Limitations & Architectural Scope

> [!CAUTION]
> **Static Analysis Scope Disclaimer**:
> This evaluation benchmarks APICompass against deterministic AST patterns and documented Stripe API contracts. It **does NOT certify or prove runtime correctness for all arbitrary Python code**.

Key known limitations:
1. **Dynamic Metaprogramming & Reflection**: Code utilizing runtime reflection (e.g. `getattr(stripe, "Charge")`, dynamic `globals()`, or monkey-patched modules) cannot be deterministically resolved by AST inspection and will abstain.
2. **Dynamic Unpack Content Inspection**: When `**kwargs` unpacking is detected (`EVAL-25`), APICompass conservatively avoids claiming missing required parameters. However, static analysis cannot guarantee that the runtime dictionary actually contains the required keys without whole-program symbolic execution.
3. **Inter-procedural Cross-Module Constant Propagation**: APICompass evaluates assignments intra-procedurally. Variables imported across modules without static initialization are treated as dynamic expressions.

---

## 8. Verification Commands & Audit Logs

- **Dedicated Benchmark Runner**:
  ```bash
  PYTHONPATH=backend .venv/bin/python3 backend/evaluation/runner.py
  ```
  *Result*: **26 / 26 cases passed (100.0%)**.
- **Pytest Dataset Suite**:
  ```bash
  PYTHONPATH=backend .venv/bin/pytest backend/tests/test_evaluation_dataset.py -v
  ```
  *Result*: **26 passed in 1.39s**.
- **Full Backend Regression Suite**:
  ```bash
  MOCK_MODE=true .venv/bin/pytest backend/tests -m "not live_smoke"
  ```
  *Result*: **636 passed, 3 deselected, 0 failed in 31.32s**.
