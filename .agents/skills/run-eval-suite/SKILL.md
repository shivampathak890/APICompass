---
name: run-eval-suite
description: >-
  Execute, inspect, and benchmark the APICompass Curated Evaluation Suite (EVAL-01 to EVAL-26).
  Use this skill whenever the user asks to run benchmarks, evaluate accuracy, test the 26 evaluation cases,
  verify contract detection rules, or check for regression in API verdict adjudications.
---

# Run Evaluation Suite Skill

This skill provides procedures and CLI tooling to run and analyze the 26 curated ground-truth evaluation cases defined in `backend/evaluation/dataset.py` and documented in `docs/CURATED_EVALUATION_DATASET.md`.

## Overview of Evaluation Cases

The suite validates the deterministic API contract verification pipeline across key categories:
- **Clean usage**: Correct modern Stripe API patterns (`EVAL-01`, `EVAL-13`, `EVAL-18`, `EVAL-20`, `EVAL-22`, `EVAL-24`, `EVAL-25`)
- **Verified issues**: Deprecated parameters (`EVAL-02`), unsupported parameters (`EVAL-03`), deprecated operations (`EVAL-04`), constraint violations (`EVAL-05`), type errors (`EVAL-19`), mixed issues (`EVAL-21`)
- **Abstention & Quarantine**: Invalid syntax (`EVAL-09`), non-API functions (`EVAL-08`), ambiguous docs (`EVAL-11`), retrieval failures (`EVAL-12`), mock quarantine guarantees (`EVAL-17`), comment immunity (`EVAL-23`), indeterminate dynamic calls (`EVAL-26`)

Expected baseline: **26/26 Passed (100.0%)**.

---

## Running the Suite

### Run All 26 Cases
```bash
./.venv/bin/python .agents/skills/run-eval-suite/scripts/run_eval.py
```
Or directly via module:
```bash
PYTHONPATH=backend ./.venv/bin/python -m evaluation.runner
```

### Run a Specific Case
```bash
./.venv/bin/python .agents/skills/run-eval-suite/scripts/run_eval.py --case EVAL-17
```

### Filter by Expected Verdict
```bash
# Only run cases expecting "issues_found"
./.venv/bin/python .agents/skills/run-eval-suite/scripts/run_eval.py --verdict issues_found

# Only run cases expecting "unable_to_verify"
./.venv/bin/python .agents/skills/run-eval-suite/scripts/run_eval.py --verdict unable_to_verify
```

### Output as JSON
```bash
./.venv/bin/python .agents/skills/run-eval-suite/scripts/run_eval.py --json
```

---

## Verifying Results

1. **Pass Rate**: Must be 100% (26/26). If any case fails, the script exits with non-zero code `1`.
2. **Failure Analysis**: When a case fails, inspect the `failure_reasons` printed beneath the case row. Check whether the failure was due to:
   - Verdict discrepancy (e.g., expected `clean`, got `issues_found`).
   - Finding category mismatch.
   - Verification status mismatch (`verified` vs `mock_quarantined` vs `unverified`).

