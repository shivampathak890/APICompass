# APICompass — Comprehensive Current State Audit & Architectural Review

**Repository**: [https://github.com/shivampathak890/APICompass.git](https://github.com/shivampathak890/APICompass.git)  
**Branch**: `feature/verification-integrity`  
**Current Date**: October 21, 2026  
**Status**: Comprehensive Baseline Verification Completed  

---

## 1. Executive Summary & Technology Stack

APICompass is a zero-execution API contract verification engine specifically designed for Python code interacting with the Stripe API ecosystem. It strictly separates deterministic static analysis and evidence verification from probabilistic LLM explanations: **"The model proposes; deterministic code decides."**

### Verified Technology Stack

| Layer | Technology | Version | Key Configuration / Details |
| :--- | :--- | :--- | :--- |
| **Backend Runtime** | Python | `3.14.4` | CPython runtime on Linux/WSL; uses passive AST parsing |
| **Backend Framework**| FastAPI & Uvicorn | `0.115.6` / `0.34.0` | ASGI application with Lifespan management & SSE |
| **Validation** | Pydantic v2 | `>=2.10.4,<3.0.0` | Strict schemas (`extra="forbid"`) & `pydantic-settings` |
| **HTTP Client** | HTTPX | `0.28.1` | Async HTTP client with timeouts, retry, and circuit breaker |
| **AI Integration** | OpenAI SDK | `3.33.0` | Optional advisory reasoning; input secret-scrubbed |
| **Persistence** | SQLite 3 | WAL mode | Immutable audit ledger at `data/apicompass.db` |
| **Testing** | Pytest & pytest-asyncio | `8.3.4` / `0.25.0` | 664 tests across unit, integration, and security suites |
| **Frontend Runtime** | Node.js / Vite | Node v20 / Vite `5.4.21` | Vite build toolchain with proxying to port 8000 |
| **Frontend Framework**| React 18 & TypeScript | `18.3.1` / `5.6.3` | Functional React with strict TypeScript typing |
| **UI Components** | Tailwind & Monaco | Tailwind `3.4.15` | Monaco Editor (`@monaco-editor/react 4.7.0`), Lucide Icons |
| **Containerization** | Docker Compose | Compose v2 | Non-root containers (`appuser:1000`, `node:1000`) |
| **CI / CD** | None | N/A | No `.github/workflows` configured yet |

---

## 2. Comprehensive 20-Point Technical Inspection

### 1. Repository Structure
- Root directories: `backend/` (FastAPI app & tests), `frontend/` (React SPA), `data/` (SQLite DB & logs), `docs/` (24 technical specifications), `.agents/` (Antigravity agent skills), `scratch/` (temporary scripts).
- Standard root configuration files: `.dockerignore`, `.env`, `.env.example`, `.gitignore`, `docker-compose.yml`, `pytest.ini`, `skills-lock.json`.

### 2. README and Setup Instructions
- File: [`README.md`](README.md)
- Covers: 30-second walkthrough, static analysis architecture, zero-execution security guarantees, local setup instructions, Docker Compose stack commands, API endpoint catalog, and evaluation benchmarks.
- Verified accurate with minor exception: instructions specify `./.venv/bin/pytest`, which previously hit a shebang directory discrepancy.

### 3. Backend Entry Points
- File: [`backend/app/main.py`](backend/app/main.py)
- Factory function: `create_app()` initializes CORS middleware with explicit origins (rejects wildcards), lifespan context manager executing `init_db()` migrations, global secret-scrubbing exception handlers, and API router mounting under `/api/v1`.

### 4. API Routes
- File: [`backend/app/api/router.py`](backend/app/api/router.py) mounts [`backend/app/api/v1/`](backend/app/api/v1/):
  - `POST /api/v1/analyze`: Unified AST + documentation retrieval + evidence adjudication pipeline.
  - `POST /api/v1/analyze/stream`: Real-time Server-Sent Events (SSE) streaming adjudication.
  - `POST /api/v1/analyze/python`: Standalone zero-execution AST analysis.
  - `POST /api/v1/identify/python`: Structured Stripe API call and argument identification.
  - `POST /api/v1/project/analyze`: Multi-file dependency graph analysis.
  - `POST /api/v1/fixes/propose`: AST-verified migration diff generation.
  - `GET /api/v1/docs/retrieve`, `GET /api/v1/docs/search`: Documentation retrieval endpoints.
  - `GET /api/v1/health`: System health, DB connection, and provider status.
  - `GET /api/v1/scans`, `GET /api/v1/scans/{id}`, `DELETE /api/v1/scans/{id}`: Audit history endpoints.

### 5. Request and Response Schemas
- Directory: [`backend/app/schemas/`](backend/app/schemas/)
- All schemas use Pydantic v2 with strict typing and `extra="forbid"`:
  - `ast_analysis.py`: `ApiCandidate`, `CallInfo`, `AnalyzePythonRequest`, `AnalyzePythonResponse`.
  - `contract.py`: `ExtractedContract`, `ContractFindingCandidate`.
  - `documentation.py`: `NormalizedEvidence`, `DocRetrievalRequest`, `DocRetrievalResponse`.
  - `evidence.py`: `AnalysisRequest`, `AnalysisReport`, `VerifiedIssue`, `CandidateAssessment`.
  - `fix_proposal.py`: `ProposeFixRequest`, `FixProposalResponse`.
  - `health.py`: `HealthResponse`, `ProviderStatus`.
  - `scan_history.py`: `ScanSummaryItem`, `ScanListResponse`.
  - `stream.py`: `StreamProgressEvent`.

### 6. Analysis Engine
- File: [`backend/app/services/evidence/adjudicator.py`](backend/app/services/evidence/adjudicator.py)
- Core workflow: AST Analysis ➔ Call Identification ➔ (Optional) Scrubbed AI Reasoning ➔ Documentation Retrieval ➔ Contract Extraction ➔ Contract Matching ➔ Substring Quote Verification ➔ Mock Quarantine Guard ➔ Conservative Adjudication.
- Emits three mutually exclusive verdicts: `clean`, `issues_found`, `unable_to_verify`.

### 7. Python AST Analysis
- File: [`backend/app/services/python_ast_analyzer.py`](backend/app/services/python_ast_analyzer.py)
- Uses built-in `ast.parse` and custom `ast.NodeVisitor` classes (`AstImportVisitor`, `AstCandidateVisitor`).
- Extracts module imports, alias mapping (`import stripe as s`), class definitions, function calls, positional and keyword arguments, line and column numbers.
- Handles invalid syntax cleanly without crashing, returning `status="syntax_error"`.

### 8. API Contract Detection
- Files: [`backend/app/services/evidence/contract_matcher.py`](backend/app/services/evidence/contract_matcher.py), [`contract_extractor.py`](backend/app/services/evidence/contract_extractor.py), [`contract_comparator.py`](backend/app/services/evidence/contract_comparator.py)
- Extracts contracts from official docs: required parameters, deprecated parameters, unsupported parameters, parameter types, deprecation replacements.
- Compares observed AST arguments against extracted contracts and generates findings candidates with line coordinates.

### 9. Evidence Retrieval and Validation
- Directory: [`backend/app/services/documentation/`](backend/app/services/documentation/)
- Adapters: `TinyFishLiveRetriever` (live external API) and `TinyFishMockRetriever` (deterministic offline fixtures).
- Security Guard: `validate_destination_url` enforces HTTPS and allows only `APPROVED_DOC_HOSTS` (`stripe.com`, `docs.stripe.com`, `github.com`).
- Quote Verifier ([`quote_verifier.py`](backend/app/services/evidence/quote_verifier.py)): Validates that quotes are exact byte substrings of retrieved documentation and matches SHA-256 content hashes.

### 10. AI / LLM Integration
- Directory: [`backend/app/services/llm/`](backend/app/services/llm/)
- Module: `reasoning_service.py`, `provider.py`, `secret_scrubber.py`.
- Security: `scrub_secrets` strips Stripe API keys (`sk_live_*`, `sk_test_*`, `whsec_*`), Bearer tokens, passwords, and prompt injection delimiters before dispatch.
- Boundary: AI explanations are classified as advisory and cannot override deterministic contract verdicts.

### 11. Database and Persistence
- Files: [`backend/app/db/connection.py`](backend/app/db/connection.py), [`backend/app/db/migrations.py`](backend/app/db/migrations.py), [`backend/app/repositories/scan_repository.py`](backend/app/repositories/scan_repository.py)
- Engine: SQLite with WAL mode, foreign key enforcement, and busy timeout (5000ms).
- Tables: `schema_migrations`, `scans`, `scan_evidence`, `scan_findings`, `scan_fix_proposals`, `scan_project_files`.
- Zero-Retention Privacy: Source code is never stored in SQLite; only SHA-256 hash and byte length are persisted.

### 12. Frontend Components
- Directory: [`frontend/src/components/`](frontend/src/components/)
- Components:
  - `MonacoPythonEditor.tsx`: Monaco editor for Python code with line decoration markers.
  - `FindingCard.tsx`: Rich cards rendering findings, severity badges, official quotes, canonical URLs, SHA-256 hashes, and proposed diff migrations.
  - `LiveScanProgress.tsx`: Real-time SSE stage progress indicator.
  - `ProjectAnalysisView.tsx`: Multi-file code analysis workspace.
  - `ScanHistoryView.tsx`: Interactive audit log ledger.
  - `StatusCard.tsx`: Service status bar in footer.

### 13. Frontend / Backend Communication
- Files: [`frontend/src/services/api.ts`](frontend/src/services/api.ts), [`sseParser.ts`](frontend/src/services/sseParser.ts)
- Communication: Typed Fetch API for REST requests and `ReadableStreamDefaultReader` for SSE streaming over `/api/v1/analyze/stream`.
- Vite dev server proxies `/api` requests to `http://127.0.0.1:8000`.

### 14. Dependency Files
- Backend: [`backend/requirements.txt`](backend/requirements.txt) (pinned runtime packages), [`backend/requirements-dev.txt`](backend/requirements-dev.txt) (pytest packages).
- Frontend: [`frontend/package.json`](frontend/package.json) and [`frontend/package-lock.json`](frontend/package-lock.json).

### 15. Environment Configuration
- Files: [`.env.example`](.env.example), [`.env`](.env)
- Settings managed by `backend/app/config.py` using `pydantic-settings`:
  - `APP_ENV`, `MOCK_MODE`, `API_HOST`, `API_PORT`, `FRONTEND_ORIGIN`, `APPROVED_DOC_HOSTS`, `TINYFISH_API_KEY`, `LLM_PROVIDER`, `APICOMPASS_DB_PATH`, `SOURCE_RETENTION_ENABLED`.

### 16. Automated Tests
- Directory: [`backend/tests/`](backend/tests/)
- Total: 36 test files containing **664 automated test cases**.
- Coverage: AST parsing, contract extraction, quote verification, mock quarantine integrity, secret scrubbing, network resilience, streaming SSE, SQLite persistence, and health endpoints.
- Current status: **661 passed, 3 skipped (live network smoke tests), 0 failed**.

### 17. Fixtures and Sample Inputs
- Files: [`backend/evaluation/dataset.py`](backend/evaluation/dataset.py), [`dataset.json`](backend/evaluation/dataset.json), [`backend/app/services/documentation/mock_adapter.py`](backend/app/services/documentation/mock_adapter.py)
- Ground-truth evaluation dataset: 26 curated cases (`EVAL-01` to `EVAL-26`) with explicit expected verdicts and contract categories.
- Current evaluation result: **26/26 Passed (100.0%)**.

### 18. Docker Configuration
- Files: [`docker-compose.yml`](docker-compose.yml), [`backend/Dockerfile`](backend/Dockerfile), [`frontend/Dockerfile`](frontend/Dockerfile)
- Multi-container setup for `backend` (port 8000) and `frontend` (port 5173).
- Security: Dedicated non-root users (`appuser:1000`, `node:1000`), zero-dependency Python/wget health checks.

### 19. CI/CD Configuration
- Status: **Not Present**.
- No `.github/workflows/` directory currently exists in the repository.

### 20. Security-Sensitive Operations
- **Zero Execution Guarantee**: User Python code is strictly parsed into AST data and walked; never executed, imported, or evaluated.
- **SSRF Defense**: Doc retrieval URLs validated against `APPROVED_DOC_HOSTS` allowlist; private IP ranges and HTTP schemes blocked.
- **Secret Scrubbing**: Hardcoded API keys, tokens, and prompt injection tokens redacted before reaching any external service.
- **Privacy Enforcement**: Submitted source code is not stored in SQLite audit records.

---

## 3. Major Features Audit & Classification

| Feature | File Path | Status | Dependencies | Existing Tests | Known Limitations | Potential Defects | Recommended Next Step |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AST Analysis Engine** | `backend/app/services/python_ast_analyzer.py` | `IMPLEMENTED` | Python `ast` | `test_ast_analyzer*.py` | Scoped to Python AST; dynamic metaprogramming indeterminate | Complex multi-hop variable aliases may evaluate as indeterminate | Expand symbol resolution for deep nested variable assignments |
| **API Call Identifier** | `backend/app/services/identification/call_identifier.py` | `IMPLEMENTED` | `ast` | `test_api_call_identification.py` | Scoped to Stripe ecosystem calls | Unrecognized third-party libraries flagged as ambiguous | Add pattern support for additional Stripe submodules |
| **Contract Extractor** | `backend/app/services/evidence/contract_extractor.py` | `IMPLEMENTED` | `re` | `test_contract_matcher.py` | Regex/heuristics on doc excerpts | Freeform unstructured documentation without clear keywords | Refine parameter extraction patterns for complex table layouts |
| **Contract Matcher** | `backend/app/services/evidence/contract_matcher.py` | `IMPLEMENTED` | Schemas | `test_contract_matcher.py` | Requires matched evidence items | Incomplete excerpts must abstain rather than hallucinate | Maintain strict abstention invariants |
| **Quote Verifier** | `backend/app/services/evidence/quote_verifier.py` | `IMPLEMENTED` | `hashlib` | `test_evidence_engine.py` | Exact substring match required | Minor doc formatting changes require updated hash/text | Keep exact substring verification strictly enforced |
| **Evidence Adjudicator** | `backend/app/services/evidence/adjudicator.py` | `IMPLEMENTED` | Matcher, Verifier | `test_evidence_adjudication_strengthened.py` | Deterministic court rules | None detected; 100% eval benchmark pass rate | Validate resilience against malformed evidence payloads |
| **Streaming Adjudicator** | `backend/app/services/evidence/stream_adjudicator.py` | `IMPLEMENTED` | `asyncio` | `test_streaming.py` | SSE stream protocol | Client disconnects need graceful task cancellation | Test client disconnect mid-stream |
| **Fix Proposer** | `backend/app/services/fixes/fix_proposer.py` | `IMPLEMENTED` | `ast`, `difflib`| `test_fix_proposals.py` | Currently supports Charge ➔ PaymentIntent migrations | Syntax errors in proposed replacement trigger abstention | Expand migration templates for other deprecated Stripe parameters |
| **TinyFish Live Retrieval** | `backend/app/services/documentation/tinyfish_adapter.py` | `IMPLEMENTED` | `httpx` | `test_tinyfish_*.py` | Requires valid external API key | Rate limits or network dropouts trigger circuit breaker | Verify circuit breaker recovery transitions |
| **Offline Mock Retrieval** | `backend/app/services/documentation/mock_adapter.py` | `IMPLEMENTED` | Dict fixtures | `test_mock_mode_audit.py` | Mock findings strictly quarantined | Cannot generate verified production findings | Preserve strict mock quarantine badges |
| **LLM Reasoning Service** | `backend/app/services/llm/reasoning_service.py` | `PARTIALLY IMPLEMENTED` / `MOCK/DEMO` | `openai`, Scrubber | `test_llm_reasoning*.py` | Disabled by default; OpenAI required for live mode | Model hallucinations must remain advisory | Test secret scrubbing against exotic prompt injection attempts |
| **SQLite Audit Ledger** | `backend/app/repositories/scan_repository.py` | `IMPLEMENTED` | `sqlite3` | `test_scan_persistence.py` | Local disk SQLite | Concurrent file writes handled by WAL and busy timeout | Benchmark WAL concurrent write throughput |
| **Monaco Python Editor** | `frontend/src/components/MonacoPythonEditor.tsx` | `IMPLEMENTED` | Monaco React | Manual / E2E | Large vendor chunk (4.45 MB) | Slow initial bundle load on constrained network | Implement code splitting / lazy loading for Monaco editor |
| **Real-time SSE UI** | `frontend/src/components/LiveScanProgress.tsx` | `IMPLEMENTED` | SSE Parser | Manual / E2E | Relies on active SSE connection | UI fallback if stream drops | Add reconnect / retry handling in frontend SSE listener |
| **Scan History View** | `frontend/src/components/ScanHistoryView.tsx` | `IMPLEMENTED` | React | Manual / E2E | Paginated in batches of 10 | Large history deletion operations | Add batch delete / clear history button in UI |
| **Multi-File Project View**| `frontend/src/components/ProjectAnalysisView.tsx` | `IMPLEMENTED` | React | `test_project_analysis*.py` | Scoped to small-to-medium project repos | Memory usage on very large multi-file trees | Verify multi-file project drag-and-drop file upload |
| **CI/CD Pipeline** | `.github/workflows/` | `PROPOSED` | GitHub Actions | None | Not yet configured | Unverified pull requests could break test suite | Implement GitHub Actions CI workflow |

---

## 4. Work Division & Execution Plan

### **Developer 1: Backend Verification, Validation, Integrity & Security**
1. **AST & Edge Case Hardening**:
   - Verify handling of complex nested calls, chained invocations, dynamic `**kwargs`, and variable reassignments.
   - Verify that invalid syntax never panics the backend.
2. **Deterministic Court & Quarantine Integrity**:
   - Verify that mock evidence is strictly quarantined in all code paths.
   - Audit quote verification: ensure zero tolerance for partial matches, fuzzy matches, or AI hallucinated excerpts.
3. **SSRF & Security Review**:
   - Validate SSRF allowlist boundaries (`stripe.com`, `docs.stripe.com`, `github.com`).
   - Validate that credentials (`sk_live_*`, `sk_test_*`) are scrubbed before any external invocation.
   - Re-verify SQLite schema to guarantee zero raw source code storage.
4. **Backend Resilience & Benchmarks**:
   - Test TinyFish circuit breaker under simulated 429 rate limits and network timeouts.
   - Run and preserve 100% pass rate on the 26-case curated evaluation suite (`runner.py`).

### **Developer 2: Frontend, UI, User Workflow & Frontend Testing**
1. **Monaco Editor & Performance Optimization**:
   - Optimize frontend build bundle size; configure code-splitting for Monaco language workers to reduce the 4.45 MB bundle.
   - Verify line marker squiggles and line jump functionality from Finding Cards into Monaco editor lines.
2. **Live SSE Streaming UX**:
   - Ensure smooth transitions across all SSE stages (`accepted`, `static_analysis`, `doc_retrieval`, `evidence_verification`, `completed`).
   - Verify graceful reconnection or error display if backend stream terminates prematurely.
3. **Finding Cards & Diff Visualizer**:
   - Verify visual rendering of `VERIFIED` (green), `MOCK QUARANTINE` (yellow), and `UNABLE TO VERIFY` (gray) badges.
   - Verify that clicking "Apply Proposed Fix" cleanly replaces the target code snippet in the Monaco editor.
4. **Scan History & Project Management**:
   - Test scan history inspection, pagination, and deletion workflows in the UI.
   - Verify multi-file project analysis view with sample multi-file Python packages.

### **Shared Responsibilities: Integration, CI/CD, Documentation & Release**
1. **API Contract Verification**:
   - Coordinate request/response schema alignment between FastAPI models and TypeScript types.
2. **CI/CD Automation**:
   - Implement GitHub Actions workflow (`.github/workflows/ci.yml`) to automatically execute backend pytest suites and frontend build checks on every pull request.
3. **End-to-End Smoke & Demonstration**:
   - Execute the 3-minute demonstration plan (`docs/THREE_MINUTE_DEMO_PLAN.md`).
   - Verify both Offline Mock Mode (`MOCK_MODE=true`) and Live Mode (`MOCK_MODE=false`).
4. **Documentation & Release Artifacts**:
   - Verify that all setup steps in `README.md` and `docs/SETUP.md` match actual environment execution.
