# APICompass — Backend API Contract Specification

**Target Audience:** Developer 2 (Frontend & User Experience), API Integration Engineers  
**Specification Version:** `1.0.0`  
**Base URL:** `http://localhost:8000/api/v1`  
**OpenAPI / Swagger UI:** `http://localhost:8000/docs`  
**OpenAPI Specification JSON:** `http://localhost:8000/openapi.json`  
**Core Product Principle:** *"The model proposes. Deterministic code decides."*

---

## 1. Architectural Invariants & Global Rules

All frontend requests and integrations must strictly respect the following backend invariants:

1. **Strict Payload Filtering (`extra="forbid"`)**:  
   Every Pydantic request model enforces `extra="forbid"`. Any extraneous, unexpected, or misspelled properties in the JSON payload will result in an immediate **HTTP 422 Unprocessable Entity** error. Do not send undocumented fields.

2. **Input Bounds & Size Constraints**:
   - Single-file Python source: Maximum **100,000 characters** (`100 KB`).
   - Project multi-file upload: Maximum **20 files** (`MAX_PROJECT_FILES = 20`), maximum **100,000 bytes** per individual file, maximum cumulative project size **500,000 bytes** (`500 KB`).
   - Filenames and project paths must not contain directory traversal sequences (`..`, leading `/`, or absolute root specifiers).

3. **Deterministic Error Handling & Secret Scrubbing**:
   - Errors consistently return the standard `ErrorResponse` model containing `error_code`, `status_code`, `timestamp`, and `errors`.
   - **Secret Sanitization**: All error messages and logs automatically redact Stripe live/test secret keys (`sk_live_[0-9a-zA-Z]{24,}`, `sk_test_[0-9a-zA-Z]{24,}`, `rk_live_*`, `rk_test_*`).
   - Internal 500 exceptions are trapped and sanitized; sensitive stack traces or environment variables are never exposed across HTTP boundaries.

4. **Zero Code Execution**:
   - The backend is an offline, static AST analysis and contract adjudication engine. It **never** executes, imports, or runs user-submitted code in a Python runtime.

5. **Authentication & Authorization**:
   - Currently, all `/api/v1/*` routes are unauthenticated for local development and desktop prototype execution.
   - CORS is configured to accept requests from `http://localhost:5173` (Vite) and `http://localhost:3000`.

6. **Supported Ecosystems**:
   - Default: `stripe`
   - Specifying an unsupported ecosystem string results in graceful analysis returns with `verdict="unsupported_ecosystem"` or `verdict="unable_to_verify"`.

---

## 2. API Endpoints Reference

### 2.1 System & Health

#### `GET /api/v1/health`
Checks backend operational status, active configuration flags, and subsystem readiness.

- **Method**: `GET`
- **Path**: `/api/v1/health`
- **Auth**: None
- **Request Body**: None
- **Success Status**: `200 OK`
- **Response Schema (`HealthResponse`)**:
```json
{
  "status": "healthy",
  "service": "APICompass Backend",
  "version": "0.1.0",
  "timestamp": "2026-10-21T05:30:00Z",
  "mock_mode": true,
  "database_status": "ok",
  "provider_status": {
    "tinyfish": "configured",
    "llm": "disabled"
  }
}
```

---

### 2.2 Python AST Inspection

#### `POST /api/v1/analyze/python`
Performs standalone zero-execution AST syntax and structural parsing on a Python source snippet.

- **Method**: `POST`
- **Path**: `/api/v1/analyze/python`
- **Request Body (`AnalyzePythonRequest`)**:
  - `source` *(string, required)*: Python code snippet (1 to 100,000 characters).
  - `filename` *(string, optional, default: `"input.py"`)*: Virtual filename for source location tracking.
- **Success Status**: `200 OK`
- **Response Schema (`AnalyzePythonResponse`)**:
  - `success` *(boolean)*: True if AST parsing succeeded without fatal syntax errors.
  - `filename` *(string)*: Filename analyzed.
  - `total_lines` *(integer)*: Total line count of submitted source.
  - `imports` *(array)*: Extracted module import nodes (`module`, `name`, `alias`, `location`).
  - `functions` *(array)*: Extracted function definitions (`name`, `is_async`, `parameters`, `location`).
  - `classes` *(array)*: Extracted class definitions.
  - `calls` *(array)*: All AST call expressions detected in the file.
  - `syntax_error` *(object | null)*: Syntax error details if AST parsing failed (`message`, `lineno`, `col_offset`, `text`).

#### `POST /api/v1/identify/python`
Extracts and isolates candidate third-party API invocations (e.g. `stripe.Charge.create`) from Python source code without performing evidence adjudication.

- **Method**: `POST`
- **Path**: `/api/v1/identify/python`
- **Request Body (`IdentifyApiCallsRequest`)**:
  - `source` *(string, required)*: Python source code (1 to 100,000 characters).
  - `filename` *(string, optional, default: `"input.py"`)*: Filename.
  - `ecosystem` *(string, optional, default: `"stripe"`)*: Target ecosystem filter.
- **Success Status**: `200 OK`
- **Response Schema (`IdentifyApiCallsResponse`)**:
  - `total_candidates` *(integer)*: Number of API candidate calls found.
  - `candidates` *(array)*: Identified API candidates (`candidate_id`, `receiver`, `target_name`, `call_expr`, `args`, `kwargs`, `location`).
  - `syntax_error` *(object | null)*: Present if AST parse failed.

---

### 2.3 Comprehensive Verification & Adjudication

#### `POST /api/v1/analyze`
The primary unified analysis and adjudication endpoint. Parses Python source code, extracts API candidates, fetches or retrieves official documentation evidence, deterministically verifies contracts, computes verdict status, and persists an audit record to the local SQLite database.

- **Method**: `POST`
- **Path**: `/api/v1/analyze`
- **Request Body (`AnalysisRequest`)**:
  - `source` *(string, required)*: Python source code (1 to 100,000 chars).
  - `filename` *(string, optional, default: `"snippet.py"`)*: Filename.
  - `ecosystem` *(string, optional, default: `"stripe"`)*: Target API ecosystem.
  - `force_mock` *(boolean, optional, default: `false`)*: Force offline mock documentation retrieval fixtures even if live API keys are configured.
- **Success Status**: `200 OK`
- **Response Schema (`AnalysisReport`)**:
  - `verdict` *(string)*: Master verdict: `"clean"`, `"issues_found"`, `"syntax_error"`, `"unable_to_verify"`, or `"unsupported_ecosystem"`.
  - `result_state` *(string)*: Alias mirror of `verdict`.
  - `engine_version` *(string)*: Verification engine version (e.g. `"0.1.0"`).
  - `filename` *(string)*: File evaluated.
  - `total_lines` *(integer)*: Line count.
  - `evidence_trust` *(string)*: `"live_verified"`, `"mock_fixture"`, or `"untrusted_or_unavailable"`.
  - `is_mock` *(boolean)*: True if mock evidence fixtures were used during retrieval.
  - `summary` *(string)*: Concise human-readable summary of adjudication findings.
  - `checks_performed` *(array of strings)*: List of verification pipeline steps executed.
  - `verified_issues` *(array of `VerifiedIssue`)*: Deterministically confirmed contract violations.
  - `ai_suggestions` *(array of `AiSuggestion`)*: Non-binding AI-generated hypotheses (separated from deterministic issues).
  - `unresolved_candidates` *(array of strings)*: IDs of API calls that could not be fully proven or disproven.
  - `candidate_assessments` *(array of `CandidateAssessment`)*: Full per-candidate audit breakdown.
  - `evidence_items` *(array of `DocEvidence`)*: Retrieved documentation fragments with SHA-256 hashes and canonical URLs.
  - `limitations_and_caveats` *(array of strings)*: Explicit uncertainty notices and boundary conditions.
  - `syntax_error` *(object | null)*: Python syntax error details if code could not be parsed.
  - `llm_reasoning_status` *(string)*: `"enabled"`, `"disabled"`, `"skipped"`, or `"error"`.
  - `llm_reasoning_summary` *(string | null)*: Summary of LLM reasoning if enabled.
  - `disclaimer` *(string)*: Required product disclaimer (*"The model proposes; deterministic code decides..."*).
  - `scan_id` *(string)*: Unique scan audit identifier (e.g. `"scan_b32f21c3632a409b"`).
  - `persistence_status` *(string)*: `"saved"`, `"skipped"`, or `"error"`.

#### `POST /api/v1/analyze/stream`
Server-Sent Events (SSE) streaming endpoint providing real-time pipeline execution progress milestones, followed by the final identical `AnalysisReport` payload.

- **Method**: `POST`
- **Path**: `/api/v1/analyze/stream`
- **Content-Type**: `text/event-stream`
- **Request Body (`AnalysisRequest`)**: Identical to `POST /api/v1/analyze`.
- **Stream Event Format**:
  - `event: progress`
    - `data`: `{"stage": "<STAGE_NAME>", "progress": <0.0-1.0>, "message": "<STATUS_TEXT>"}`
    - Stages: `parsing`, `identifying_calls`, `retrieving_evidence`, `matching_contracts`, `llm_reasoning`, `adjudicating`
  - `event: complete`
    - `data`: Full JSON serialization of `AnalysisReport`.

#### `POST /api/v1/analyze/project`
Multi-file Python project static verification endpoint. Resolves cross-file module imports, builds an inter-file dependency graph, analyzes each file, aggregates candidates across the project, and provides both whole-project and per-file verdicts.

- **Method**: `POST`
- **Path**: `/api/v1/analyze/project`
- **Request Body (`ProjectAnalysisRequest`)**:
  - `project_name` *(string, optional, default: `"python_project"`)*: Project identifier (max 100 chars).
  - `ecosystem` *(string, optional, default: `"stripe"`)*: Ecosystem name.
  - `files` *(array of `ProjectFileItem`, required, 1 to 20 files)*:
    - `path` *(string, required)*: Relative file path (e.g. `"services/payments.py"`). Normalization rejects traversal attacks.
    - `content` *(string, required)*: Python file contents (max 100 KB per file).
  - `force_mock` *(boolean, optional, default: `false`)*: Force mock fixtures.
- **Success Status**: `200 OK`
- **Response Schema (`ProjectAnalysisReport`)**:
  - `project_name` *(string)*: Name of project.
  - `verdict` *(string)*: Overall project verdict (`"clean"`, `"issues_found"`, `"syntax_error"`, `"unable_to_verify"`).
  - `engine_version` *(string)*: Engine version.
  - `total_files` *(integer)*: Total files analyzed.
  - `total_lines` *(integer)*: Cumulative lines of code.
  - `parsed_files_count` *(integer)*: Successfully parsed files.
  - `syntax_errors_count` *(integer)*: Count of files with syntax errors.
  - `total_candidates` *(integer)*: Total API calls found across all files.
  - `resolved_imports_count` *(integer)*: Internal project imports successfully resolved.
  - `unresolved_imports_count` *(integer)*: Project imports that could not be mapped.
  - `external_imports_count` *(integer)*: Third-party or standard library imports.
  - `evidence_trust` *(string)*: Evidence trust tier.
  - `is_mock` *(boolean)*: True if mock evidence used.
  - `summary` *(string)*: Summary of findings.
  - `checks_performed` *(array of strings)*: Project checks executed.
  - `relationships` *(array)*: Inter-file and external import relationships.
  - `files` *(array)*: Per-file breakdown (`path`, `parse_status`, `syntax_error`, `imports`, `functions`, `calls`).
  - `verified_issues` *(array)*: Aggregated verified issues across all files.
  - `ai_suggestions` *(array)*: Aggregated AI suggestions.
  - `candidate_assessments` *(array)*: Per-candidate assessments across all files.
  - `evidence_items` *(array)*: Retrieved documentation items.
  - `limitations_and_caveats` *(array of strings)*: Limitations (e.g., partial analysis due to syntax error in one file).
  - `scan_id` *(string)*: Unique scan audit identifier.
  - `persistence_status` *(string)*: `"saved"`, `"skipped"`, or `"error"`.

---

### 2.4 Documentation Retrieval & Search

#### `POST /api/v1/docs/retrieve`
Retrieves and extracts structured contract documentation for a specific API endpoint or symbol.

- **Method**: `POST`
- **Path**: `/api/v1/docs/retrieve`
- **Request Body (`DocRetrievalRequest`)**:
  - `query` *(string, required)*: API symbol query (e.g. `"stripe.Charge.create"`, 1 to 500 chars).
  - `url` *(string, optional)*: Specific documentation URL to fetch.
  - `ecosystem` *(string, optional, default: `"stripe"`)*: Target ecosystem.
  - `force_mock` *(boolean, optional, default: `false`)*: Force mock fixtures.
- **Success Status**: `200 OK`
- **Response Schema (`DocRetrievalResponse`)**:
  - `evidence` *(DocEvidence | null)*: Structured evidence item with `source_url`, `content_sha256`, `headings`, `parameters`, `required_fields`, `deprecation_notices`.
  - `status` *(string)*: `"success"`, `"mock"`, `"not_found"`, or `"error"`.
  - `message` *(string | null)*: Retrieval status message.
  - `duration_ms` *(float)*: Latency of retrieval in milliseconds.

#### `POST /api/v1/docs/search`
Searches documentation index for candidate API reference pages.

- **Method**: `POST`
- **Path**: `/api/v1/docs/search`
- **Request Body (`DocSearchRequest`)**:
  - `query` *(string, required)*: Search query string.
  - `limit` *(integer, optional, default: 5, min: 1, max: 20)*: Maximum results.
  - `ecosystem` *(string, optional, default: `"stripe"`)*: Target ecosystem.
- **Success Status**: `200 OK`
- **Response Schema (`DocSearchResponse`)**:
  - `query` *(string)*: Query executed.
  - `total_results` *(integer)*: Result count.
  - `results` *(array of `DocSearchResultItem`)*: List of search hits with `title`, `url`, `snippet`.

---

### 2.5 Remediation & Fix Proposals

#### `POST /api/v1/fixes/propose`
Proposes safe, verified remediation code diffs for a detected contract issue.

- **Method**: `POST`
- **Path**: `/api/v1/fixes/propose`
- **Request Body (`ProposeFixRequest`)**:
  - `source` *(string, required)*: Original Python source code.
  - `issue` *(VerifiedIssue, required)*: The verified issue to remediate.
  - `evidence` *(DocEvidence, optional)*: Official documentation contract evidence supporting the fix.
- **Success Status**: `200 OK`
- **Response Schema (`FixProposalResponse`)**:
  - `proposal_id` *(string)*: Unique identifier.
  - `proposed_source` *(string)*: Remediated Python code.
  - `diff` *(string)*: Unified diff representation of the fix.
  - `explanation` *(string)*: Explanation of changes.
  - `confidence` *(float)*: Confidence score between 0.0 and 1.0.
  - `verification_status` *(string)*: `"verified_safe"`, `"heuristic"`, or `"unverified"`.

---

### 2.6 Persistence & Scan History

#### `GET /api/v1/scans`
Lists past scan audit records stored in the local SQLite database. Source code is never retained in the audit database.

- **Method**: `GET`
- **Path**: `/api/v1/scans`
- **Query Parameters**:
  - `limit` *(integer, optional, default: 20, min: 1, max: 100)*: Items per page.
  - `offset` *(integer, optional, default: 0, min: 0)*: Pagination offset.
  - `ecosystem` *(string, optional)*: Filter by ecosystem.
- **Success Status**: `200 OK`
- **Response Schema (`ScanListResponse`)**:
  - `total_count` *(integer)*: Total recorded scans.
  - `items` *(array of `ScanSummaryItem`)*: Scan entries with `scan_id`, `created_at`, `filename`, `verdict`, `evidence_trust`, `is_mock`, `total_lines`, `total_issues`, `source_hash`.

#### `GET /api/v1/scans/{scan_id}`
Retrieves complete historical audit metadata for a specific scan.

- **Method**: `GET`
- **Path**: `/api/v1/scans/{scan_id}`
- **Path Parameters**:
  - `scan_id` *(string, required)*: Scan ID (format: `scan_[a-f0-9]{16}`).
- **Success Status**: `200 OK`
- **Error Status**: `404 Not Found` if scan does not exist.
- **Response Schema (`HistoricalScanDetail`)**:
  - `scan_id`, `created_at`, `filename`, `verdict`, `evidence_trust`, `is_mock`, `source_hash`, `summary`, `verified_issues_count`, `checks_performed`, `limitations_and_caveats`, `serialized_report`.

#### `DELETE /api/v1/scans/{scan_id}`
Deletes a scan audit record from the database.

- **Method**: `DELETE`
- **Path**: `/api/v1/scans/{scan_id}`
- **Path Parameters**:
  - `scan_id` *(string, required)*: Scan ID.
- **Success Status**: `200 OK`
- **Error Status**: `404 Not Found` if scan does not exist.
- **Response Schema (`DeleteScanResponse`)**:
  - `deleted` *(boolean)*: True if record was removed.
  - `scan_id` *(string)*: Deleted scan identifier.

---

## 3. Concrete Request & Response JSON Examples

### Example 1: Valid Analysis Request
```json
POST /api/v1/analyze HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "source": "import stripe\n\ndef create_customer(email: str):\n    return stripe.Customer.create(email=email)\n",
  "filename": "customer_service.py",
  "ecosystem": "stripe",
  "force_mock": false
}
```

---

### Example 2: Successful Clean Analysis Response (`verdict="clean"`)
*Occurs when code contains valid, supported API calls that match official documentation with zero contract violations.*
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "verdict": "clean",
  "result_state": "clean",
  "engine_version": "0.1.0",
  "filename": "customer_service.py",
  "total_lines": 4,
  "evidence_trust": "live_verified",
  "is_mock": false,
  "summary": "Static contract verification passed for 1 in-scope API call(s). No contract violations or deprecations detected.",
  "checks_performed": [
    "Python AST syntax validation",
    "Python AST call graph extraction",
    "API candidate identification",
    "Documentation evidence retrieval",
    "API contract matching",
    "Deterministic quotation verification"
  ],
  "verified_issues": [],
  "ai_suggestions": [],
  "unresolved_candidates": [],
  "candidate_assessments": [
    {
      "candidate_id": "cand_001",
      "target_name": "create",
      "receiver": "stripe.Customer",
      "call_expr": "stripe.Customer.create(email=email)",
      "source_location": {
        "lineno": 4,
        "col_offset": 11,
        "end_lineno": 4,
        "end_col_offset": 45
      },
      "status": "verified_clean",
      "verification_status": "confirmed_clean",
      "evidence_match": {
        "candidate_id": "cand_001",
        "matched_operation": "stripe.Customer.create",
        "evidence_id": "ev_8b21a0f4439c",
        "source_url": "https://docs.stripe.com/api/customers/create",
        "canonical_url": "https://docs.stripe.com/api/customers/create",
        "source_title": "Create a customer | Stripe API Reference",
        "retrieval_status": "live",
        "retrieved_at": "2026-10-21T08:00:00Z",
        "is_mock": false,
        "completeness": "complete_contract",
        "is_ambiguous": false,
        "match_rationale": "Matched official documentation for 'stripe.Customer.create'."
      },
      "verified_quotes": [
        {
          "quote_text": "Creates a new customer object.",
          "source_url": "https://docs.stripe.com/api/customers/create",
          "character_offset": 120,
          "is_exact_match": true,
          "hash_sha256": "8f434346648f6b96df89dda901c5176b10f600aec66b197e4137d84f6a524ea0"
        }
      ],
      "issues": [],
      "caveats": []
    }
  ],
  "evidence_items": [
    {
      "evidence_id": "ev_8b21a0f4439c",
      "ecosystem": "stripe",
      "package": "stripe",
      "source_url": "https://docs.stripe.com/api/customers/create",
      "canonical_url": "https://docs.stripe.com/api/customers/create",
      "title": "Create a customer | Stripe API Reference",
      "content_excerpt": "Creates a new customer object. Accepts parameters including email, name, description...",
      "retrieved_at": "2026-10-21T08:00:00Z",
      "provider": "tinyfish_live",
      "status": "success",
      "is_mock": false,
      "source_trust": "live_verified",
      "doc_version": "2024-04-10",
      "content_sha256": "4a7263b6521a09d...",
      "headings": ["Create a customer", "Arguments", "Returns"],
      "parameters": ["email", "name", "description", "phone", "metadata"],
      "required_fields": [],
      "deprecation_notices": [],
      "code_examples": []
    }
  ],
  "limitations_and_caveats": [
    "Verification is strictly static and evaluates only detected Stripe SDK calls.",
    "Dynamic runtime arguments, reflection, and network exceptions are not evaluated."
  ],
  "syntax_error": null,
  "llm_reasoning_status": "disabled",
  "llm_reasoning_summary": null,
  "disclaimer": "The model proposes; deterministic code decides. A 'clean' verdict indicates only that supported checks found no verified contract violations within the analyzed scope. It does not guarantee absence of other bugs.",
  "scan_id": "scan_b32f21c3632a409b",
  "persistence_status": "saved"
}
```

---

### Example 3: Response Containing Findings (`verdict="issues_found"`)
*Occurs when live documentation proves contract violations (e.g. removed legacy parameter or deprecated method).*
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "verdict": "issues_found",
  "result_state": "issues_found",
  "engine_version": "0.1.0",
  "filename": "charges.py",
  "total_lines": 3,
  "evidence_trust": "live_verified",
  "is_mock": false,
  "summary": "1 verified contract violation(s) confirmed against official documentation.",
  "checks_performed": [
    "Python AST syntax validation",
    "Python AST call graph extraction",
    "API candidate identification",
    "Documentation evidence retrieval",
    "API contract matching",
    "Deterministic quotation verification"
  ],
  "verified_issues": [
    {
      "issue_id": "iss_a92ef81c",
      "rule_id": "CONTRACT-001",
      "rule_category": "api_contract",
      "severity": "high",
      "status": "confirmed",
      "title": "Deprecated Parameter: 'source' in stripe.Charge.create",
      "message": "Parameter 'source' is deprecated in Stripe API version 2024-04-10. Use PaymentIntents with payment methods instead.",
      "file_path": "charges.py",
      "location": {
        "lineno": 3,
        "col_offset": 4,
        "end_lineno": 3,
        "end_col_offset": 71
      },
      "code_snippet": "stripe.Charge.create(amount=1000, currency='usd', source='tok_123')",
      "confidence": 1.0,
      "evidence": {
        "candidate_id": "cand_001",
        "matched_operation": "stripe.Charge.create",
        "evidence_id": "ev_078c3b9ac7d9bf51",
        "source_url": "https://docs.stripe.com/api/charges/create",
        "canonical_url": "https://docs.stripe.com/api/charges/create",
        "source_title": "Create a charge | Stripe API Reference",
        "retrieval_status": "live",
        "retrieved_at": "2026-10-21T08:15:00Z",
        "is_mock": false,
        "completeness": "complete_contract",
        "is_ambiguous": false,
        "match_rationale": "Official documentation explicitly marks parameter 'source' as deprecated."
      },
      "verified_quote": {
        "quote_text": "The source parameter is deprecated. We recommend using Payment Intents instead.",
        "source_url": "https://docs.stripe.com/api/charges/create",
        "character_offset": 542,
        "is_exact_match": true,
        "hash_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      },
      "suggested_fix": "Migrate to stripe.PaymentIntent.create(amount=1000, currency='usd', payment_method='pm_123').",
      "suggested_fix_diff": null
    }
  ],
  "ai_suggestions": [],
  "unresolved_candidates": [],
  "candidate_assessments": [
    {
      "candidate_id": "cand_001",
      "target_name": "create",
      "receiver": "stripe.Charge",
      "call_expr": "stripe.Charge.create(amount=1000, currency='usd', source='tok_123')",
      "source_location": {
        "lineno": 3,
        "col_offset": 4,
        "end_lineno": 3,
        "end_col_offset": 71
      },
      "status": "violation_confirmed",
      "verification_status": "confirmed",
      "evidence_match": {
        "candidate_id": "cand_001",
        "matched_operation": "stripe.Charge.create",
        "evidence_id": "ev_078c3b9ac7d9bf51",
        "source_url": "https://docs.stripe.com/api/charges/create",
        "canonical_url": "https://docs.stripe.com/api/charges/create",
        "source_title": "Create a charge | Stripe API Reference",
        "retrieval_status": "live",
        "retrieved_at": "2026-10-21T08:15:00Z",
        "is_mock": false,
        "completeness": "complete_contract",
        "is_ambiguous": false,
        "match_rationale": "Matched official documentation for 'stripe.Charge.create'."
      },
      "verified_quotes": [],
      "issues": [],
      "caveats": []
    }
  ],
  "evidence_items": [],
  "limitations_and_caveats": [
    "Verification is strictly static and evaluates only detected Stripe SDK calls."
  ],
  "syntax_error": null,
  "llm_reasoning_status": "disabled",
  "llm_reasoning_summary": null,
  "disclaimer": "The model proposes; deterministic code decides. A 'clean' verdict indicates only that supported checks found no verified contract violations within the analyzed scope. It does not guarantee absence of other bugs.",
  "scan_id": "scan_e51ac33db7bf4de5",
  "persistence_status": "saved"
}
```

---

### Example 4: Response Containing No In-Scope Findings (`verdict="unable_to_verify"`)
*Occurs when code is syntactically valid Python, but contains no supported API calls.*
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "verdict": "unable_to_verify",
  "result_state": "unable_to_verify",
  "engine_version": "0.1.0",
  "filename": "math_utils.py",
  "total_lines": 2,
  "evidence_trust": "untrusted_or_unavailable",
  "is_mock": false,
  "summary": "No supported in-scope API calls detected in the submitted Python source. Verification was not performed.",
  "checks_performed": [
    "Python AST syntax validation",
    "Python AST call graph extraction",
    "API candidate identification"
  ],
  "verified_issues": [],
  "ai_suggestions": [],
  "unresolved_candidates": [],
  "candidate_assessments": [],
  "evidence_items": [],
  "limitations_and_caveats": [
    "NO_IN_SCOPE_CANDIDATES: Static AST analysis identified no supported Stripe API calls to verify.",
    "This does not certify that the submitted code is correct, bug-free, or compliant with third-party libraries outside the supported ecosystem."
  ],
  "syntax_error": null,
  "llm_reasoning_status": "disabled",
  "llm_reasoning_summary": null,
  "disclaimer": "The model proposes; deterministic code decides. A 'clean' verdict indicates only that supported checks found no verified contract violations within the analyzed scope. It does not guarantee absence of other bugs.",
  "scan_id": "scan_b32f21c3632a409b",
  "persistence_status": "saved"
}
```

---

### Example 5: Invalid Input Response (`422 Unprocessable Entity`)
*Occurs when the request body violates Pydantic constraints or includes forbidden extra fields.*
```json
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/json

{
  "detail": "Input validation failed: unknown_field: Extra inputs are not permitted",
  "error_code": "VALIDATION_ERROR",
  "status_code": 422,
  "timestamp": "2026-10-21T03:08:19.958961+00:00",
  "errors": [
    {
      "loc": [
        "body",
        "unknown_field"
      ],
      "msg": "Extra inputs are not permitted",
      "type": "extra_forbidden"
    }
  ]
}
```

---

### Example 6: Backend Failure Response (`500 Internal Server Error`)
*Occurs in the event of an unhandled backend exception. Secret keys and raw stack traces are safely scrubbed.*
```json
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
  "detail": "An internal server error occurred while processing the request. Reference ID: err_71a09dfc",
  "error_code": "INTERNAL_SERVER_ERROR",
  "status_code": 500,
  "timestamp": "2026-10-21T08:20:00.123456+00:00",
  "errors": [
    {
      "loc": ["server"],
      "msg": "Internal adjudication pipeline encountered an unexpected error.",
      "type": "server_error"
    }
  ]
}
```

---

### Example 7: Partial-Result Response (`POST /api/v1/analyze/project`)
*Occurs when a multi-file project contains some valid files and some unparseable files with syntax errors. The backend completes analysis on all valid files while isolating and reporting the broken ones.*
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "project_name": "sample_proj",
  "verdict": "unable_to_verify",
  "engine_version": "0.1.0",
  "total_files": 2,
  "total_lines": 3,
  "parsed_files_count": 1,
  "syntax_errors_count": 1,
  "total_candidates": 0,
  "resolved_imports_count": 0,
  "unresolved_imports_count": 0,
  "ambiguous_imports_count": 0,
  "external_imports_count": 1,
  "evidence_trust": "untrusted_or_unavailable",
  "is_mock": false,
  "summary": "No supported in-scope API calls detected across 2 project file(s). Verification was not performed.",
  "checks_performed": [
    "Project path safety and normalization check",
    "Zero-execution multi-file AST parsing",
    "Cross-file dependency and relationship graph resolution",
    "API candidate identification"
  ],
  "relationships": [
    {
      "source_file": "good.py",
      "target": "stripe",
      "target_file": null,
      "relationship_type": "file_imports_external",
      "imported_symbol": null,
      "alias": null,
      "status": "external",
      "reason": "External package or standard library import 'stripe'.",
      "location": {
        "lineno": 1,
        "col_offset": 0,
        "end_lineno": 1,
        "end_col_offset": 13
      }
    }
  ],
  "files": [
    {
      "path": "good.py",
      "parse_status": "success",
      "total_lines": 2,
      "syntax_error": null,
      "imports": [
        {
          "module": "stripe",
          "name": null,
          "alias": null,
          "is_from": false,
          "level": 0,
          "location": {
            "lineno": 1,
            "col_offset": 0,
            "end_lineno": 1,
            "end_col_offset": 13
          }
        }
      ],
      "functions": [
        {
          "name": "pay",
          "is_async": false,
          "parameters": [],
          "decorators": [],
          "return_annotation": null,
          "enclosing_scope": null,
          "location": {
            "lineno": 2,
            "col_offset": 0,
            "end_lineno": 2,
            "end_col_offset": 15
          }
        }
      ],
      "classes": [],
      "calls": [],
      "candidates": [],
      "relevant_literals": [],
      "defined_symbols": [
        "pay"
      ]
    },
    {
      "path": "bad.py",
      "parse_status": "syntax_error",
      "total_lines": 1,
      "syntax_error": {
        "message": "'(' was never closed",
        "lineno": 1,
        "col_offset": 18,
        "text": "def broken_syntax("
      },
      "imports": [],
      "functions": [],
      "classes": [],
      "calls": [],
      "candidates": [],
      "relevant_literals": [],
      "defined_symbols": []
    }
  ],
  "verified_issues": [],
  "ai_suggestions": [],
  "unresolved_candidates": [],
  "candidate_assessments": [],
  "evidence_items": [],
  "limitations_and_caveats": [
    "Project analysis is strictly static and zero-execution; dynamic behavior and reflection are not evaluated.",
    "Import resolution reflects syntax-level module hierarchies and does not execute package __init__ files.",
    "SYNTAX_ERRORS_IN_PROJECT: 1 file(s) contain syntax errors (bad.py). Complete whole-project verification is impossible.",
    "NO_IN_SCOPE_CANDIDATES: Static AST analysis identified no supported Stripe API calls to verify across the project."
  ],
  "disclaimer": "Multi-file project analysis is strictly static and does not execute submitted code. A 'clean' verdict applies only to in-scope API calls verified against official contracts and does not certify total project correctness, runtime behavior, or absence of other bugs.",
  "scan_id": "scan_448373dc1ac64e56",
  "persistence_status": "saved"
}
```

---

## 4. Frontend Integration Guidelines for Developer 2

### 4.1 UI Component Alignment
| Endpoint | Primary UI Component / Page | Notes for Frontend Developer |
| :--- | :--- | :--- |
| `GET /api/v1/health` | `Navbar` / System Status Indicator | Poll periodically or on page load to display live/mock engine indicators. |
| `POST /api/v1/analyze` | `SingleFileInput` / `AnalysisDashboard` | Standard single-file submission. Renders verdict badge, issue cards, and caveats. |
| `POST /api/v1/analyze/stream` | `StreamingProgressModal` / Real-Time Progress Bar | Connect via `fetch` ReadableStream or EventSource. Handle `progress` and `complete` events. |
| `POST /api/v1/analyze/project` | `ProjectUploadZone` / `ProjectResultsView` | Multi-file or zip upload. Render dependency tree, per-file status badges, and syntax errors. |
| `POST /api/v1/docs/retrieve` | `DocEvidenceInspectorModal` | Side drawer displaying retrieved Stripe API doc excerpts and SHA-256 hashes. |
| `POST /api/v1/fixes/propose` | `DiffViewerModal` / Code Remediation Pane | Displays side-by-side or unified diff of proposed code fix. |
| `GET /api/v1/scans` | `ScanHistoryTable` | Historical scans list with pagination, date formatting, and filter by ecosystem. |
| `GET /api/v1/scans/{id}` | `ScanHistoryDetailView` | Reconstructs and visualizes past scan audit reports. |
| `DELETE /api/v1/scans/{id}` | `ScanHistoryTable` (Delete button) | Deletes audit record with confirmation toast. |

### 4.2 Handling Verdict Badges in the UI
The frontend must render distinct visual badges based on the `verdict` string:
- `"clean"`: **Green Badge** (`"Verified Clean"`). Note: Display the mandatory disclaimer tooltip indicating this applies to verified API calls, not universal correctness.
- `"issues_found"`: **Red/Orange Badge** (`"Issues Detected"`). Display count of `verified_issues`.
- `"unable_to_verify"`: **Yellow/Amber Badge** (`"Unable to Verify"`). Check `is_mock` or `limitations_and_caveats` (e.g. mock fixture mode, or no in-scope API calls).
- `"syntax_error"`: **Red Badge** (`"Syntax Error"`). Highlight the line and column in the Monaco / Code editor.
- `"unsupported_ecosystem"`: **Gray Badge** (`"Unsupported Ecosystem"`). Inform user only `stripe` is currently supported.

### 4.3 Handling Strict 422 Errors
If a user submits an extra field or invalid format, the frontend will receive an HTTP 422 with `error_code: "VALIDATION_ERROR"`. Parse the `errors` array and display field-level validation messages:
```typescript
interface ErrorDetailItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}
```
Field location maps directly to form inputs: `["body", "source"]` -> `source` code editor.

---

## 5. Schema Change Log & Backward Compatibility

| Date | Endpoint / Schema | Change Type | Reason & Impact |
| :--- | :--- | :--- | :--- |
| `2026-10-21` | Initial Contract Finalization | Baseline | Documented all 12 existing endpoints against backend v0.1.0 without breaking modifications. |
