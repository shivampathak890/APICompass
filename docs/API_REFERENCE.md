# APICompass v3 — API Reference Manual

Complete reference of all HTTP endpoints, query parameters, request schemas, response models, and error behaviors supported by APICompass v3.

Base URL: `http://127.0.0.1:8000/api/v1`

---

## 1. System Health

### `GET /health`
Returns system liveness, active version, current UTC timestamp, SQLite database connectivity status, and external provider lifecycle diagnostics.

- **Method:** `GET`
- **Authentication:** None
- **Response Model:** `HealthResponse`
- **Response Codes:**
  - `200 OK`: System healthy.
- **Example Response:**
  ```json
  {
    "status": "healthy",
    "service": "apicompass-api",
    "version": "0.1.0",
    "timestamp": "2026-10-17T20:00:00.000000+00:00",
    "mock_mode": true,
    "database_status": "ok",
    "provider_status": {
      "tinyfish": "disabled",
      "llm": "disabled"
    }
  }
  ```
- **Provider Lifecycle Values:**
  - `disabled`: Feature explicitly disabled in settings.
  - `missing_credentials`: Provider selected but credentials unset or blank.
  - `configured`: Non-empty credential set. *(Note: Does not indicate upstream connectivity or validity)*.
  - `unavailable`: Circuit breaker is open or provider is in a runtime error state.

---

## 2. Static AST Analysis (Zero-Execution)

### `POST /analyze/python`
Analyzes raw Python source text using standard library `ast.parse()`. Submitted code is strictly inspected as data and is never executed.

- **Method:** `POST`
- **Request Model:** `AnalyzePythonRequest`
  - `source` (string, 1–102,400 chars, required): Python code snippet.
  - `filename` (string, max 255 chars, default: `"input.py"`): File identifier.
- **Response Model:** `AnalyzePythonResponse`
  - `status`: `"success"` or `"syntax_error"`.
  - `imports`: List of imported modules and aliases with line coordinates.
  - `calls`: Detected function and method calls.
  - `candidates`: Heuristic API candidates detected with rationales.
  - `definitions`: Functions and classes defined in the snippet.
  - `syntax_error`: Diagnostic details if parsing fails (`message`, `lineno`, `col_offset`).
- **Response Codes:**
  - `200 OK`: Analysis completed (even if syntax errors exist in the source).
  - `422 Unprocessable Entity`: Request body exceeds 100 KB limit.

---

## 3. Official Documentation Retrieval

### `POST /docs/retrieve`
Retrieves normalized evidence from approved documentation hosts. Destinations are validated against SSRF rules.

- **Method:** `POST`
- **Request Model:** `DocRetrievalRequest`
  - `ecosystem` (string, default: `"stripe"`): Target API ecosystem.
  - `package` (string, default: `"stripe"`): Package identifier.
  - `query` (optional string): Keyword search query.
  - `target_url` (optional string): Canonical documentation URL to fetch.
  - `max_results` (integer, 1–10, default: 5): Result ceiling.
- **Response Model:** `DocRetrievalResponse`
  - `status`: `"success"` or `"error"`.
  - `provider`: Provider identifier (e.g., `"tinyfish_live"`, `"tinyfish_mock"`).
  - `is_mock`: Boolean indicating whether mock fixtures were used.
  - `evidence`: Array of `NormalizedEvidence` items containing title, URL, SHA-256 excerpt hash, and content.
- **Response Codes:**
  - `200 OK`: Retrieval executed.
  - `422 Unprocessable Entity`: URL fails SSRF allowlist validation.

---

## 4. Unified Evidence Court Adjudication

### `POST /analyze`
Coordinates static AST parsing, optional advisory LLM candidate reasoning, documentation retrieval, deterministic quote verification, and Evidence Court adjudication. Automatically records an audit snapshot to SQLite.

- **Method:** `POST`
- **Request Model:** `AnalysisRequest`
  - `source` (string, 1–102,400 chars, required): Python code.
  - `filename` (string, max 255 chars, default: `"snippet.py"`): Filename.
  - `ecosystem` (string, default: `"stripe"`): Target ecosystem.
- **Response Model:** `AnalysisReport`
  - `verdict`: `"clean"`, `"issues_found"`, or `"unable_to_verify"`.
  - `evidence_trust`: `"official"` or `"mock_fixture"`.
  - `is_mock`: Boolean flag.
  - `scan_id`: Persisted audit record ID (e.g., `"scan_41efc2323b0246b1"`).
  - `persistence_status`: `"saved"` or `"failed"`.
  - `verified_issues`: Array of quote-verified contract violations.
  - `candidate_assessments`: Assessment per candidate call.
  - `ai_suggestions`: Advisory hypotheses (`"AI suggestion — not verified"`).
  - `evidence_items`: Documentation items evaluated.
  - `limitations_and_caveats`: Explicit analysis scope boundaries.
- **Response Codes:**
  - `200 OK`: Adjudication completed.
  - `422 Unprocessable Entity`: Payload > 100 KB or invalid parameters.

---

## 5. Real-Time Streaming Verification

### `POST /analyze/stream`
Executes adjudication with real-time Server-Sent Events (SSE) progress updates.

- **Method:** `POST`
- **Request Model:** `AnalysisRequest` (identical to `/analyze`)
- **Response:** `text/event-stream`
- **Event Lifecycle Stages:**
  1. `accepted`: Request accepted.
  2. `static_analysis_started` / `static_analysis_completed`: AST parsing.
  3. `ai_reasoning_started` / `ai_reasoning_completed`: Advisory LLM (if enabled).
  4. `documentation_retrieval_started` / `documentation_retrieval_completed`: Documentation fetching.
  5. `evidence_verification_started` / `evidence_verification_completed`: Deterministic quote verification.
  6. `persistence_started` / `persistence_completed`: SQLite audit recording.
  7. `completed`: Terminal event delivering the complete `AnalysisReport`.

---

## 6. Multi-File Project Analysis

### `POST /analyze/project`
Analyzes multi-file Python projects without runtime execution. Resolves relative and absolute internal imports, detects circular dependencies, parses files independently, and evaluates aggregated candidates.

- **Method:** `POST`
- **Request Model:** `ProjectAnalysisRequest`
  - `project_name` (string, 1–100 chars, required): Project identifier.
  - `ecosystem` (string, default: `"stripe"`): Target ecosystem.
  - `files` (array of `ProjectFileInput`, 1–20 items, required):
    - `path` (string, relative, $\le 255$ chars): e.g., `"services/payment.py"`.
    - `content` (string, $\le 100$ KB): Python source code.
- **Response Model:** `ProjectAnalysisReport`
  - `verdict`: Project-level verdict (`"clean"`, `"issues_found"`, `"unable_to_verify"`).
  - `files`: Per-file analysis summaries with candidate counts and syntax statuses.
  - `dependency_graph`: Resolved internal imports and detected circular dependency cycles.
  - `verified_issues`: Verified violations annotated with originating `file_path`.
  - `syntax_errors_count`: Number of files with syntax errors.
  - `unresolved_imports_count`: Number of internal imports that could not be resolved.
- **Response Codes:**
  - `200 OK`: Project analysis completed.
  - `422 Unprocessable Entity`: Exceeds 20 files, exceeds 500 KB total size, invalid path characters (`..`, `\`, absolute paths), or duplicate file paths.

---

## 7. Evidence-Gated Fix Proposals

### `POST /fixes/propose`
Generates an evidence-gated fix proposal for a specific AST candidate with in-memory static re-verification. Local files are never modified.

- **Method:** `POST`
- **Request Model:** `ProposeFixRequest`
  - `source` (string, 1–102,400 chars, required): Original code.
  - `candidate_id` (string, required): Authentic candidate identifier.
  - `filename` (string, default: `"snippet.py"`): Filename.
  - `ecosystem` (string, default: `"stripe"`): Target ecosystem.
  - `issue_id` (optional string): Linked issue ID.
- **Response Model:** `FixProposalResponse`
  - `status`: `"evidence_supported"`, `"mock_evidence_only"`, `"insufficient_evidence"`, or `"syntax_check_failed"`.
  - `unified_diff`: Standard unified diff of the proposed modification.
  - `proposed_source`: Complete source text with proposed edit applied.
  - `syntax_valid`: Boolean confirming whether proposed code parses into an AST.
  - `reverification_status`: Static re-verification outcome (`"verified_resolved"`, `"reverification_inconclusive"`, etc.).
  - `remaining_uncertainties`: Aspects not verified by static analysis.
- **Response Codes:**
  - `200 OK`: Proposal generated.
  - `422 Unprocessable Entity`: Unknown candidate or payload limit exceeded.

---

## 8. Scan Audit History

### `GET /scans`
Lists historical scan audit records with bounded pagination and optional filtering.

- **Method:** `GET`
- **Query Parameters:**
  - `limit` (integer, 1–100, default: 20): Items per page.
  - `offset` (integer, $\ge 0$, default: 0): Page offset.
  - `verdict` (optional string): Filter by verdict (`clean`, `issues_found`, `unable_to_verify`).
  - `ecosystem` (optional string): Filter by ecosystem (e.g., `stripe`).
  - `source_sha256` (optional string): Filter by source SHA-256 fingerprint.
- **Response Model:** `ScanListResponse`
  - `items`: Array of scan summaries (ID, created_at, verdict, source_sha256, source_chars, is_mock, total_issues).
  - `total`: Total matching records.
  - `has_more`: Boolean pagination flag.

### `GET /scans/{scan_id}`
Retrieves a complete historical audit snapshot by ID. Does not re-trigger live network calls or LLM requests.

- **Method:** `GET`
- **Path Parameters:**
  - `scan_id` (string, required): Format `^scan_[a-zA-Z0-9_\-]{8,64}$`.
- **Response Model:** `HistoricalScanDetail` (annotated with `is_historical: true`).
- **Response Codes:**
  - `200 OK`: Scan found.
  - `400 Bad Request`: Malformed `scan_id`.
  - `404 Not Found`: Scan not found.

### `DELETE /scans/{scan_id}`
Transactionally deletes a historical scan record and cascades to remove associated evidence and findings entries.

- **Method:** `DELETE`
- **Path Parameters:**
  - `scan_id` (string, required): Valid scan ID.
- **Response Model:** `DeleteScanResponse` (`success: true`, `scan_id`, `deleted_at`).
- **Response Codes:**
  - `200 OK`: Scan deleted.
  - `400 Bad Request`: Malformed `scan_id`.
  - `404 Not Found`: Scan not found.
