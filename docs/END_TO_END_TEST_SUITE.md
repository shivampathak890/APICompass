# APICompass End-to-End Test Suite Documentation

## 1. Executive Summary

APICompass features a comprehensive end-to-end integration and system test suite validating the entire lifecycle of an analysis request:
```
Python code submission
    -> Safe AST parsing (zero execution)
    -> Stripe API call identification
    -> Documentation resolution (Registry fast-path & TinyFish Search)
    -> Live documentation fetch (TinyFish Fetch API)
    -> Contract extraction & quote verification
    -> Evidence-based adjudication
    -> SQLite audit record persistence (secrets scrubbed)
    -> API response / Server-Sent Events (SSE)
    -> Frontend findings display
```

The test suite runs deterministically without requiring a live TinyFish API key, uses synthetic HTTP response fixtures, enforces complete database isolation (`test_e2e.db` / `tmp_path`), and verifies all 10 core system invariants.

---

## 2. Test Architecture & Environment Isolation

### 2.1 Deterministic Mock HTTP Responses
- **No Live TinyFish Key Required**: Automated tests patch `httpx.AsyncClient` methods selectively so that requests to TinyFish endpoints (`api.fetch.tinyfish.ai`, `api.search.tinyfish.ai`) return predictable synthetic payloads while internal ASGI test client requests to FastAPI (`http://testserver`) route directly to the local application.
- **Realistic Markdown Payloads**: Synthetic responses model actual Stripe documentation Markdown (`LIVE_PAYMENT_INTENTS_DOC_MARKDOWN`, `LIVE_CHARGES_DOC_MARKDOWN`), containing exact parameter headings, required markers, type signatures, and deprecation notices.

### 2.2 Database Isolation
- **Test-Specific SQLite Instances**: All automated tests override `settings.APICOMPASS_DB_PATH` with `tmp_path / "test.db"` (Pytest) or `data/test_e2e.db` (Playwright E2E).
- **Default Database Preservation**: The developer's primary database (`data/apicompass.db`) is never touched, polluted, or wiped during test execution.
- **Zero Secret Retention Verification**: Tests verify that raw API keys (e.g., `sk_live_SUPER_SECRET_...`) and submitted source code are never stored in the database. Only `source_sha256` and `source_length` are persisted.

---

## 3. Test Matrix & Verification Coverage

### 3.1 Backend End-to-End Pipeline Suite (`backend/tests/test_end_to_end_pipeline.py`)

| Test Identifier | Tested Workflow & Verification Invariant | Status |
| :--- | :--- | :---: |
| `test_01_e2e_pipeline_with_registry_fast_path_and_verified_issue` | Complete 10-step pipeline detecting a real Stripe issue via live documentation. Verifies `issues_found`, `live_official_source`, exact quotation verification, and parameter extraction. | **PASSED** |
| `test_02_e2e_pipeline_clean_code_verified_clean` | Compliant Stripe API calls verified against live docs produce `clean` verdict and `no_issue_detected` without false warnings. | **PASSED** |
| `test_03_e2e_pipeline_dynamic_search_fallback` | APIs not present in local static registry fall back to dynamic TinyFish search before fetching documentation. | **PASSED** |
| `test_04_e2e_pipeline_live_failure_abstains_without_false_issues` | Upstream TinyFish 500 server error produces honest `unable_to_verify` abstention with `DOCUMENTATION_MISSING` instead of false positive warnings. | **PASSED** |
| `test_05_e2e_pipeline_mock_mode_quarantine_enforced` | Strict mock quarantine: when running in mock mode, findings are quarantined (`MOCK_EVIDENCE_ONLY`) and can never be reported as live-verified issues. | **PASSED** |
| `test_06_e2e_pipeline_unsupported_api_abstains_honestly` | Unsupported Stripe APIs (e.g. `stripe.Terminal.Reader.create`) produce honest abstention (`UNSUPPORTED_OPERATION`) without crashing. | **PASSED** |
| `test_07_e2e_pipeline_safe_ast_parsing_zero_execution` | Harmful submitted code (`os.system('rm -rf /')`, infinite loops) is statically parsed via AST only and never executed. | **PASSED** |
| `test_08_e2e_pipeline_llm_cannot_independently_create_verified_issue` | Advisory LLM reasoning cannot create or promote findings without deterministic contract matcher verification. | **PASSED** |
| `test_09_e2e_streaming_pipeline_sse_events` | Server-Sent Events (SSE) emit structured progress stages (`accepted` -> `static_analysis` -> `doc_retrieval` -> `evidence_verification` -> `completed`). | **PASSED** |
| `test_10_e2e_http_api_preserves_locations_and_source_urls` | Full HTTP `POST /api/v1/analyze` preserves exact line numbers (`lineno=4`, `col_offset=9`), code fragments, canonical URLs, and parameters. | **PASSED** |
| `test_11_e2e_malformed_upstream_responses_handled_gracefully` | Malformed upstream responses (HTML `502 Bad Gateway`, non-list results, missing fields) safely abstain without 500 crashes. (4 parameterizations) | **PASSED** |
| `test_12_e2e_invalid_syntax_halts_with_exact_location` | Python syntax errors safely halt analysis with exact syntax error location (`line=2`, `offset=1`) and zero code execution. | **PASSED** |
| `test_13_e2e_non_stripe_functions_never_generate_false_warnings` | Unrelated Python code with common method names (`db.create()`, `db.delete()`) never generates false Stripe warnings. | **PASSED** |
| `test_14_e2e_database_isolation_and_secret_scrubbing` | Isolated test database verification: confirmed table schema contains no `source_code` or `api_key` columns and stores only SHA-256 hashes. | **PASSED** |
| `test_15_e2e_upstream_network_timeout_produces_honest_uncertainty` | Upstream network timeouts (`httpx.TimeoutException`) produce honest uncertainty and safe abstention. | **PASSED** |

### 3.2 Frontend End-to-End Suite (`frontend/e2e/`)

| Test Suite | Coverage & Invariants | Result |
| :--- | :--- | :---: |
| `primary_journey.spec.ts` | 1. Initial interface rendering and Stripe/Python scope disclosure.<br>2. Analysis execution with live/mock indicator.<br>3. Accurate progress state display during analysis.<br>4. Verified finding display with exact line numbers and source URLs.<br>5. Code correction and re-analysis flow. | **5/5 PASSED** |
| `findings_interface.spec.ts` | 1. Traceable finding cards with severity/impact classification.<br>2. Verified vs unverified suggestion badge differentiation.<br>3. Code excerpt & documented requirement presentation.<br>4. Usable external documentation source links.<br>5. "No issues detected" disclaimer covering only performed checks. | **5/5 PASSED** |
| `state_handling.spec.ts` | 1. Empty code submission validation.<br>2. Python syntax error feedback with exact line highlights.<br>3. Upstream TinyFish failure recovery message without leaking secrets.<br>4. Single-click submission lock preventing duplicate requests.<br>5. Streaming connection interruption graceful fallback. | **5/5 PASSED** |

---

## 4. Overall Test Execution Results

- **End-to-End Pipeline Tests**: 18 passed in 2.62s.
- **Backend Complete Suite**: 607 passed, 2 skipped in 27.33s.
- **Frontend Playwright Tests**: 15 passed across 3 browser suites.
- **Frontend Production Build**: Zero TypeScript errors (`tsc && vite build` succeeded).

---

## 5. Uncovered Paths & Edge Cases

The test suite thoroughly covers all primary and defensive paths. The following edge conditions represent uncovered or deferred scenarios:

1. **Multi-Page Documentation Pagination**:
   - *Current Implementation*: TinyFish Fetch retrieves single canonical documentation pages. Very large multi-page API documentations that paginate across multiple URLs are fetched per explicit endpoint URL rather than traversing deep multi-page linked graphs.
   - *Risk*: Low for Stripe API reference endpoints, which maintain self-contained reference pages per resource (e.g., `/api/payment_intents/create`).
2. **Upstream CAPTCHA or Anti-Bot Challenges**:
   - *Current Implementation*: Non-JSON or HTML challenge pages trigger the malformed response handler, which catches non-JSON text, logs a warning, and transitions safely to `unable_to_verify` (`DOCUMENTATION_MISSING`).
   - *Risk*: Handled safely (no crashes or false positives), but requires developer intervention if an upstream proxy blocks requests.
3. **Complex Cross-File Dynamic Metaprogramming**:
   - *Current Implementation*: Cross-file analysis resolves explicit `import` and `from ... import` statements. Dynamic runtime metaprogramming (`getattr(stripe, "Charge")`, dynamic `__import__`) remains intentionally out-of-scope for static AST analysis and is classified honestly as unresolved/unsupported.

---

## 6. Integration Risks & Mitigations

| Risk | Impact | Implemented Mitigation |
| :--- | :--- | :--- |
| **Upstream Provider Outage / Rate Limit** | Client requests fail or hang | Enforced finite HTTP timeouts (5s), exponential backoff circuit breaker, and automatic fallback to honest abstention state (`unable_to_verify`). |
| **Mock Evidence Leakage** | Mock fixtures misattributed as live official documentation | Enforced strict mock quarantine: `is_mock=True` cascades through all evidence and finding models. Mock fixtures can never produce `verified` issues. |
| **Database Corruption / Schema Drift** | Startup crash or failed scan persistence | Deterministic SQLite schema versioning (`PRAGMA user_version`) and idempotent migration runner. Persistence failures never break analysis responses. |
| **Client Stalling on SSE Interruption** | UI displays infinite spinner | SSE streaming includes client-side timeout guards and terminal event detection, ensuring spinners always terminate with clear status badges. |
| **Sensitive Code or Key Leakage** | Leaked secrets in logs or history | `secret_scrubber` filters known API key patterns (`sk_live_...`, `Bearer ...`). The SQLite database schema stores only `source_sha256` and `source_length`, never storing source code. |
