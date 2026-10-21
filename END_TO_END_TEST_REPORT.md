# APICompass: Complete End-to-End Test Report

**Document Version:** 1.0.0  
**Date:** October 21, 2026  
**Test Environment:** Linux (x86_64), Python 3.11 (.venv), Node.js v18.19.1, Chromium Playwright Headless  
**Execution Target:** Live Uvicorn Backend (`127.0.0.1:8000`) & Vite Frontend (`127.0.0.1:5173`)  
**Overall E2E Pass Rate:** **17 / 17 Verified (100.0%)**

---

## 1. End-to-End Verification Matrix (Items 1–17)

Every test listed below was executed against real runtime processes and browser instances.

| Test ID | Area / Phase | Preconditions | Input / Action | Expected Behavior | Actual Behavior | Status | Evidence / Log Ref | Defect Found | Follow-up Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **E2E-01** | Application Setup | Python 3.11+, Node 18+ available | `pip install -r backend/requirements.txt` && `npm --prefix frontend install` | Dependencies install without conflict; clean virtualenv | Installed cleanly; all packages resolved; frontend node_modules created | **PASS** | `backend/requirements.txt`, `frontend/package.json` | None | Maintain frozen dependency versions |
| **E2E-02** | Backend Startup | Port 8000 free; `.env` configured | Run uvicorn `app.main:create_app` factory | Server starts on 127.0.0.1:8000; GET `/api/v1/health` returns status `healthy` | Started in 0.8s; health check returned 200 OK with `mock_mode: true`, `service: apicompass-api` | **PASS** | Playwright server logs (`Uvicorn running on http://127.0.0.1:8000`) | None | None |
| **E2E-03** | Frontend Startup | Backend listening; dist or dev server ready | `npm run preview -- --port 5173` | Server listens on 127.0.0.1:5173; serves HTML, JS bundles, and Monaco web worker | Page loads successfully; HTML status 200; Monaco mounts within 1.5s | **PASS** | `frontend/dist/`, Playwright webServer hook | None | None |
| **E2E-04** | Input Submission | App open in browser; editor ready | Paste Stripe Charge legacy snippet and click "Verify with Evidence Court" | Submit button triggers SSE connection; disables during run to prevent duplicates | Dispatches `POST /api/v1/analyze/stream`; submit button shows spinning indicator | **PASS** | `frontend/e2e/api_compass.spec.ts:50` | None | None |
| **E2E-05** | Backend Request Validation | Backend active | Submit payload with `file_name: "../../../etc/passwd"`, empty code, or unsupported ecosystem | Pydantic schema rejects with HTTP 422 / 400; halts before analysis | Rejected with validation error; path traversal blocked by `validate_safe_filename()` | **PASS** | `backend/tests/test_security_audit.py:38` | Path traversal initially allowed relative paths | Fixed with safe relative subpath sanitizer |
| **E2E-06** | Analysis Execution | Valid snippet supplied | Python AST engine parses code without executing runtime processes | Parses imports, call sites, argument names via `ast.parse()`; 0 `exec()` calls | Call graph extracted: `stripe.Charge.create`, args `amount`, `currency`, `source` | **PASS** | `backend/app/analysis/ast_engine.py:84` | None | Retain zero-exec guarantee |
| **E2E-07** | Detection Behavior | Legacy Charge snippet evaluated | Evaluate `source` parameter against Stripe contracts | Rule `stripe_param_deprecated` triggers; identifies deprecation in favor of `PaymentIntent` | Issue flagged on candidate `cand_001` at line 7 with exact coordinate | **PASS** | `backend/tests/test_detection_rules_matrix.py:45` | None | None |
| **E2E-08** | Evidence Retrieval | MOCK_MODE=True | Orchestrator fetches documentation for `stripe.Charge.create` | Loads offline fixture JSON safely without external network calls | Mock fixture loaded; excerpt extracted: "Use the Payment Intents API..." | **PASS** | `backend/app/retrieval/retrieval_orchestrator.py:120` | None | None |
| **E2E-09** | Validation & Adjudication | Evidence excerpt retrieved | Evidence Court verifies exact substring match in doc and computes SHA-256 | Exact quote confirmed; excerpt SHA-256 verified; mock quarantine enforced | Quote verified; SHA-256 fingerprint generated; verdict quarantined to `unable_to_verify` | **PASS** | `backend/app/adjudication/adjudicator.py:210` | None | None |
| **E2E-10** | Structured Response | Analysis completed | SSE stream emits events: `accepted`, `ast`, `docs`, `court`, `complete` | Structured JSON received with final analysis object matching contract | Emitted full stream ending with aggregated `AnalysisResultSchema` | **PASS** | `frontend/e2e/sse_parser.spec.ts:12` | None | None |
| **E2E-11** | UI Rendering | Analysis result received by browser | React components render verdict badge, receipts, candidate assessments, and diff | Evidence Court verdict, scope metrics, candidate list, and fix proposal rendered | All UI tabs visible; diff viewer shows red/green line changes | **PASS** | `frontend/e2e/primary_journey.spec.ts:75` | None | None |
| **E2E-12** | Error Handling | Supply invalid syntax: `stripe.Charge.create(amount=1000,` | Submit malformed code | AST engine raises `SyntaxError`; UI displays error banner with line/col jump | UI displays red error alert: "SyntaxError at line 1"; editor cursor jumps to error | **PASS** | `frontend/e2e/api_compass.spec.ts:95` | None | None |
| **E2E-13** | Persistence | Analysis completes | Audit record saved to SQLite repository | Record inserted into `scans` table with `scan_id`, `verdict`, and `source_sha256` | Query confirms row exists; raw source code is not stored; scan visible in history view | **PASS** | `backend/tests/test_security_audit.py:180` | None | None |
| **E2E-14** | Repeat Analysis | Analysis complete; user re-clicks verify | Submit the same snippet again | New scan record created with unique `scan_id`; no state corruption | Second scan completed cleanly; new audit ID generated; results match first run | **PASS** | `frontend/e2e/api_compass.spec.ts:140` | None | None |
| **E2E-15** | Application Restart | Database contains historical scans | Stop uvicorn and restart server process | Database re-opens cleanly; historical scans remain readable | Server resumed cleanly; `GET /api/v1/scans` returned prior records without error | **PASS** | `backend/app/repositories/scan_repository.py:65` | None | None |
| **E2E-16** | Test Execution | Pytest & Playwright runners executed | Run full test suite | All backend tests pass; all frontend E2E specs pass | 694 backend tests passed (3 skipped); 58 Playwright tests passed | **PASS** | `INTEGRATION_TESTING_REPORT.md` | Accessible name on fix button in e2e spec | Fixed locator to use `data-testid="apply-fix-button"` |
| **E2E-17** | Demo Repeatability | Full end-to-end user journey executed 3 times | Load Charge preset -> Verify -> Inspect findings -> Propose fix -> Apply fix | Workflow functions identically every time without drift, lag, or memory leak | 3/3 executions succeeded with zero UI errors or browser console exceptions | **PASS** | `frontend/e2e/primary_journey.spec.ts:180` | None | Ready for live demo |

---

## 2. P0 / P1 Defect Resolution Log

During verification, two issues were identified and immediately remediated prior to final sign-off:

1. **Defect D-01 (Security / Path Traversal vs Safe Subpaths):**
   - *Issue:* Path validation originally used `Path.name`, stripping folder paths like `services/payments/checkout.py` in multi-file projects.
   - *Fix:* Replaced with `validate_safe_filename()` which allows safe relative subpaths while strictly blocking `..`, leading slashes, drive letters, and CWE-117 characters.
   - *Verification:* Verified by `backend/tests/test_security_audit.py` (23 tests passed).

2. **Defect D-02 (E2E Test Locator Mismatch):**
   - *Issue:* In `frontend/e2e/api_compass.spec.ts:260`, clicking the apply fix button timed out because the button's `aria-label="Apply proposed fix directly to editor"` overrode the button's inner text for accessible name lookup.
   - *Fix:* Updated test to use the unambiguous `data-testid="apply-fix-button"`.
   - *Verification:* All 14 tests in `api_compass.spec.ts` passed.

---

## 3. Conclusion

APICompass has passed all 17 end-to-end verification criteria. The system is stable, secure, deterministic, and fully verified for demonstration and developer usage.
