# APICompass: System Architecture Specification

**System Version:** 3.0 (v0.1.0)  
**Date:** October 21, 2026  
**Architectural Baseline:** FastAPI (Async Python) + React (Vite / TypeScript / Monaco) + SQLite (Audit Repository)  

---

## 1. High-Level System Architecture

APICompass is built upon a strict separation of concerns between passive code inspection, evidence retrieval, deterministic adjudication, and in-memory user assistance.

```
                           +-----------------------------------------------+
                           |          Browser Client (Vite + React)        |
                           |  - Monaco Code Editor (Zero Auto-Save)        |
                           |  - WHATWG SSE Streaming Consumer              |
                           |  - Evidence Court & Receipts Visualization    |
                           +-----------------------┬-----------------------+
                                                   │
                          HTTP / SSE (CORS Restricted, http://localhost:5173)
                                                   │
                                                   ▼
                           +-----------------------------------------------+
                           |           FastAPI Application Server          |
                           |  - Request Validation (Pydantic v2)           |
                           |  - Safe Filename & CWE-117 Sanitizer          |
                           |  - Rate Limiting & Zero Source Storage Guard  |
                           +───────┬───────────────────────────────┬───────+
                                   │                               │
            Passive AST Parsing    │                               │  Audit Metadata
                                   ▼                               ▼
     +-----------------------------------------+   +-------------------------------+
     |            AST Engine Core              |   |     SQLite Audit Repository   |
     | - Zero Execution (`ast.parse()` only)   |   | - Schema: scans, findings     |
     | - Call Graph & Receiver Resolver        |   | - Zero Source Code Stored     |
     | - Parameter & Keyword Visitor           |   | - SHA-256 Checksums           |
     +─────────────────────┬───────────────────+   +-------------------------------+
                           │
             Identified API Candidates
                           │
                           ▼
     +-----------------------------------------+
     |      Evidence Retrieval Pipeline        |
     | - TinyFish Search & Fetch Adapters      |
     | - Domain Allowlist & SSRF Defense       |
     | - Offline Mock Fixture Loader           |
     +─────────────────────┬───────────────────+
                           │
              Retrieved Doc Excerpts
                           │
                           ▼
     +-----------------------------------------+
     |         Evidence Court Engine           |
     | - Deterministic Contract Matching       |
     | - Exact Quote Verification & SHA-256    |
     | - Conservative Adjudication Rules       |
     | - Mock Mode Quarantine Guard            |
     +─────────────────────┬───────────────────+
                           │
           Adjudicated Findings & Verdicts
                           │
                           ▼
     +-----------------------------------------+
     |         Fix Proposal Generator          |
     | - Line-Bounded Unified Diff             |
     | - In-Memory Re-Verification AST Parse   |
     | - Zero Disk Overwrite Invariant         |
     +─────────────────────────────────────────+
```

---

## 2. Component Specifications

### 2.1 Backend Application Server (`backend/app/main.py`)
- **Framework:** FastAPI running on Uvicorn with ASGI architecture.
- **Factory Pattern:** `create_app()` initializes CORS middleware, rate limiters, route registrations, and lifecycle handlers.
- **Security Middleware:**
  - Strict CORS origin binding (`http://localhost:5173` by default; wildcards prohibited).
  - Secret scrubbing filter on logs and database write boundaries.
  - Path traversal and CWE-117 log injection defense via `validate_safe_filename()`.

### 2.2 Static AST Engine (`backend/app/analysis/ast_engine.py`)
- **Zero-Execution Invariant:** Source code is treated strictly as an immutable string and parsed into an Abstract Syntax Tree via Python standard library `ast.parse()`. No `eval()`, `exec()`, `importlib`, or bytecode compilation is ever invoked.
- **Call Graph Extraction:**
  - Resolves module imports (`import stripe`, `from stripe import PaymentIntent`, `import stripe as st`).
  - Resolves receiver chains and variable reassignments (`client = stripe.StripeClient(); alias = client; alias.charges.create(...)`).
  - Records line numbers, column offsets, argument names, positional argument orders, and keyword values.
  - Dynamically unwraps dictionary arguments (`**kwargs`) to prevent false positive missing-parameter alerts.

### 2.3 Evidence Retrieval Pipeline (`backend/app/retrieval/`)
- **Live Mode:** Dispatches asynchronous HTTP calls to TinyFish Search and Fetch APIs.
- **SSRF Defense:** Only domains defined in `APPROVED_DOC_HOSTS` (`stripe.com`, `docs.stripe.com`, `github.com`) are reachable. Private IPs (`10.0.0.0/8`, `192.168.0.0/16`, `127.0.0.1`, `::1`) are immediately rejected.
- **Circuit Breaker:** Fails open to `unable_to_verify` after 3 consecutive connection timeouts or failures, preventing system lockup.
- **Mock Mode:** When `MOCK_MODE=true`, bypasses external networking entirely and loads deterministic JSON fixtures from `backend/app/fixtures/`.

### 2.4 Evidence Court & Adjudication (`backend/app/adjudication/`)
- **The Core Axiom:** *"The model proposes; deterministic code decides which claims can be displayed as verified."*
- **Quotation Verification:** Every finding must cite an exact excerpt from the official contract document. The adjudicator verifies that the excerpt exists verbatim within the retrieved text and calculates its SHA-256 fingerprint.
- **Verdict Semantics:**
  - `clean`: All inspected API calls adhere to retrieved official contracts.
  - `issues_found`: One or more contract violations (unsupported/deprecated parameter, deprecated operation, or constraint violation) are confirmed by verified documentation.
  - `unable_to_verify`: Insufficient documentation, ambiguous evidence, syntax error in source, retrieval failure, or mock quarantine.

### 2.5 Mock Quarantine Guarantee
When running under `MOCK_MODE=true`:
1. `is_mock=True` is permanently stamped on the analysis context.
2. `evidence_trust` is locked to `"mock_fixture"`.
3. The Evidence Court **refuses** to issue a production `clean` or `issues_found` verdict; all verdicts are quarantined to `unable_to_verify` with an explicit amber disclaimer.
4. Fix proposals are labeled `mock_evidence_only`.

### 2.6 Persistence & Data Integrity (`backend/app/repositories/scan_repository.py`)
- **Storage:** Local SQLite database at `data/apicompass.db` (`test_e2e.db` during testing).
- **Privacy Assurance:** Raw source code is **never** written to database tables. Only metadata (`scan_id`, `file_name`, `source_sha256`, `line_count`, `char_count`, `verdict`, `duration_ms`, `findings_count`) is retained.
- **Relational Integrity:** Foreign keys link `findings` records to parent `scans` rows with `ON DELETE CASCADE`.

---

## 3. Request Lifecycle

1. **Client Submission:** User clicks "Verify with Evidence Court" in the React UI, initiating an HTTP POST request to `/api/v1/analyze/stream` with body `{ file_name, code, ecosystem }`.
2. **Schema & Input Validation:**
   - FastAPI parses body via `AnalysisRequestSchema`.
   - `validate_safe_filename()` ensures the file path contains no `..`, leading slashes, drive letters, or control characters.
   - Character count is validated against upper limits ($100{,}000$ characters).
3. **SSE Stage 1 — `accepted`:** Backend acknowledges request and yields SSE event with `scan_id`.
4. **SSE Stage 2 — `ast_complete`:** Static AST engine parses code, resolves call sites, and yields identified API candidates. If `SyntaxError` occurs, an error event is emitted immediately and the pipeline halts safely.
5. **SSE Stage 3 — `retrieval_complete`:** Documentation queries are dispatched (or loaded from mock fixtures) for each candidate.
6. **SSE Stage 4 — `court_complete`:** Evidence Court matches AST call arguments against contracts, verifies quotes, computes SHA-256 hashes, and adjudicates verdicts.
7. **SSE Stage 5 — `persistence_complete`:** Audit record is stored in SQLite (without raw source code).
8. **SSE Stage 6 — `complete`:** Final aggregated `AnalysisResultSchema` is transmitted to the client, terminating the SSE connection.

---

## 4. Frontend Architecture (`frontend/src/`)

- **UI Framework:** React 18 with TypeScript.
- **Code Editor:** `@monaco-editor/react` configured with Python syntax highlighting and custom error marker decorations.
- **Streaming Parser (`sseParser.ts`):** Custom resilient SSE parser adhering strictly to the WHATWG Server-Sent Events standard, supporting LF, CRLF, fragmented network chunks, and multi-byte UTF-8 streams.
- **Views:**
  1. `VerificationStudio`: Single-file editor, quick presets, streaming timeline, Evidence Court results, and fix proposal diff viewer.
  2. `MultiFileProject`: Multi-file tabbed editor, project dependency summary, cross-file import graph, and batch project analysis.
  3. `ScanAuditHistory`: Stored audit records table, instant historical snapshot inspection (zero re-scan requests dispatched), and permanent record deletion.
