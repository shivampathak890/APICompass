# APICompass — Backend Security and Data Integrity Review

**Audit Date:** `2026-10-21`  
**Target Systems:** FastAPI Backend Service, SQLite Audit Repository, AST Analyzer, Documentation Retrieval Service, LLM Scrubber  
**Auditor Role:** Senior Backend Verification & Security Engineer  
**Core Product Principles:**  
1. *"The model proposes. Deterministic code decides."*  
2. Zero Code Execution: Parsing Python ASTs with `ast.parse()` strictly treats source code as data; untrusted code is never compiled, imported, or executed.  
3. Source Code Privacy: User-submitted source code is never retained in database records or log files.  

---

## 1. Executive Summary & Review Scope

This review evaluates the APICompass backend implementation against security vulnerabilities, input validation weaknesses, resource exhaustion vectors, data retention and privacy breaches, and database integrity failures.

### Verified Security Posture
- **Code Execution**: Verified zero execution. No `eval()`, `exec()`, `compile()`, or `subprocess` calls exist on user-submitted source code.
- **SSRF Defense**: Strict outbound destination validation, scheme lockdown (HTTPS only), port restriction (443 only), and domain allowlisting (`APPROVED_CANONICAL_HOSTS`) block all attempts to query localhost, private RFC-1918 subnets, or cloud metadata endpoints (`169.254.169.254`).
- **Secrets & Privacy**: Sensitive API keys (`sk_live_*`, `sk_test_*`, `whsec_*`) are scrubbed before logging, error reporting, database writes, or LLM prompting. Raw source code is hashed (SHA-256) and character-counted, but never stored in the database.
- **Database Integrity**: Relational foreign key constraints (`PRAGMA foreign_keys = ON;`), WAL mode, busy timeout handling, explicit transaction rollback, and cascading deletes ensure referential consistency and prevent orphaned records.
- **Defects Fixed in Review**: Fixed **SEC-01** (Unsanitized filename input leading to CWE-117 log injection and path traversal representations across single-file endpoints).

---

## 2. In-Depth Evaluation of the 17 Security Dimensions

### 2.1 Input Validation
- **Current State**: All incoming request models (`AnalysisRequest`, `AnalyzePythonRequest`, `IdentifyApiCallsRequest`, `ProjectAnalysisRequest`, `DocRetrievalRequest`, `DocSearchRequest`, `ProposeFixRequest`) enforce `ConfigDict(extra="forbid")`. Extraneous attributes return an immediate HTTP 422.
- **Payload Limits**: Single-file source is capped at `100,000` characters (`100 KB`). Multi-file project uploads are capped at `MAX_PROJECT_FILES = 20`, `100 KB` per file, and `500 KB` total.
- **Ecosystem Strings**: Validated against regex pattern `^[a-zA-Z0-9_\-]+$` across all endpoints.
- **Evaluation**: Robust. Unsupported types or oversized payloads produce controlled validation failures before reaching internal services.

### 2.2 File Handling
- **Current State**: Zero physical temporary files are created on disk for uploaded Python code. Analysis operates entirely in-memory using Python strings and AST nodes.
- **File Descriptors**: No `open()`, `tempfile.NamedTemporaryFile()`, or disk handles are opened for user-submitted code, eliminating file descriptor leaks.
- **Evaluation**: Robust and safe.

### 2.3 Path Traversal
- **Project Analysis**: `normalize_and_validate_project_path()` strictly normalizes paths to POSIX forward slashes and rejects:
  - NUL bytes (`\0`)
  - Absolute paths (leading `/` or `\\`)
  - UNC paths (`//` or `\\\\`)
  - Drive-qualified paths (`C:`, `D:`)
  - Path traversal sequences (`..`)
  - Empty or bare `.py` files.
- **Scan IDs**: Path parameter `scan_id` on `/api/v1/scans/{scan_id}` is strictly validated against `^scan_[a-zA-Z0-9_\-]{8,64}$`.
- **Single-File Filename Inputs**: Hardened via `validate_safe_filename()`. Rejects `..`, leading `/` or `\\`, drive letters, and NUL bytes while permitting safe relative identifiers (e.g. `services/payment.py`).
- **Evaluation**: Fully protected against directory traversal attacks.

### 2.4 Uploaded Source-Code Processing
- **Current State**: Parsing is performed via standard library `ast.parse(source, filename=filename)`.
- **Syntax Errors**: Handled cleanly with line, column, and error message extraction; returns structured `syntax_error` response without crashing.
- **Complexity Guards**: Guarded against parser bombs and deeply nested structures via:
  - Source length limit: `MAX_SOURCE_CHARS = 100_000`
  - Node count limit: `MAX_AST_NODES = 10_000`
  - Nesting depth limit: `MAX_AST_DEPTH = 100`
- **Evaluation**: Controlled and resilient against algorithmic complexity denial of service.

### 2.5 Unsafe Code Execution
- **Current State**: Static inspection confirms that user-submitted code is never imported into the Python interpreter, never compiled to executable bytecode, and never passed to `eval`, `exec`, or shell processes.
- **AST Visitor Isolation**: The AST visitor inspects node types (`ast.Call`, `ast.Import`, `ast.Attribute`, `ast.Constant`) without executing any functions or evaluating runtime values.
- **Evaluation**: Zero code execution principle is fully upheld.

### 2.6 Secrets and API-Key Handling
- **Detection & Redaction**: `app.services.llm.secret_scrubber` defines regex patterns targeting:
  - Stripe live secret keys: `sk_live_[0-9a-zA-Z_\-]{16,}`
  - Stripe test secret keys: `sk_test_[0-9a-zA-Z_\-]{16,}`
  - Restricted keys: `rk_live_*`, `rk_test_*`
  - Webhook secrets: `whsec_*`
  - Publishable keys: `pk_live_*`, `pk_test_*`
  - Variable assignments: `stripe.api_key = "..."`, `api_key = "..."`, `password = "..."`
  - Authorization headers: `Bearer <token>`
- **Storage**: Service credentials (TinyFish, OpenAI) are ingested through environment variables via Pydantic `BaseSettings`. Default configuration falls back to safe offline mock fixtures when keys are absent. Credentials are never written to database tables.
- **Evaluation**: High integrity. Secrets are redacted across all loggers, exception handlers, and database writes.

### 2.7 Sensitive Logging
- **Log Scrubbing**: Log outputs flow through `scrub_secrets()`.
- **Log Injection Defense**: Filenames and query parameters are validated to reject carriage returns (`\r`) and newlines (`\n`), preventing forged log entries (CWE-117).
- **Evaluation**: Protected.

### 2.8 Error-Message Leakage
- **Exception Handlers**: Standardized handlers in `app/main.py`:
  - `RequestValidationError`: Formats 422 errors into field-level detail with secret scrubbing.
  - `StarletteHTTPException`: Formats standard HTTP exceptions with secret scrubbing.
  - `generic_exception_handler`: Catch-all handler for unhandled 500 exceptions. Generates a random reference ID (`err_<hex>`), logs the internal exception securely, and returns a generic, sanitized client message.
- **Evaluation**: Internal stack traces, database schema details, and system environment variables are never returned in HTTP responses.

### 2.9 Unrestricted Outbound Requests (SSRF)
- **Validation Engine**: `app.services.documentation.security.validate_destination_url()` implements multi-tier SSRF protection:
  - Scheme: Only `https` is permitted.
  - Port: Only port `443` (default) is permitted.
  - Host allowlist: Only approved domains (`APPROVED_CANONICAL_HOSTS`: `stripe.com`, `docs.stripe.com`, `github.com`) are allowed.
  - Prohibited hosts: Blocks `api.stripe.com`, `connect.stripe.com`, `dashboard.stripe.com` to prevent accidental real API calls.
  - IP Blocking: Rejects direct IP literals (IPv4/IPv6, octal, hex, decimal integers). Rejects loopback (`127.0.0.1`), private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), and multicast.
  - Cloud Metadata: Blocks `169.254.169.254`, `metadata.google.internal`, `metadata.azure.com`.
  - Credentials: Prohibits `user:pass@host`.
- **Evaluation**: Comprehensive SSRF protection.

### 2.10 Resource Exhaustion & Denial of Service
- **Payload Size Middleware**: `MaxPayloadSizeMiddleware` rejects requests exceeding 1 MB with HTTP 413.
- **Rate Limiter Middleware**: `RateLimiterMiddleware` enforces client request rate limits (default: 60 requests/minute per client IP) using an in-memory sliding window, returning HTTP 429 when exhausted.
- **AST Limits**: Caps file size (100 KB), AST nodes (10,000), and recursion depth (100).
- **Evaluation**: Defense-in-depth against volumetric floods and parsing complexity bombs.

### 2.11 Timeouts
- **Documentation Retrieval**: Configured with `TINYFISH_TIMEOUT = 15.0s`. Implemented using both `httpx.Timeout` and `asyncio.timeout()`.
- **LLM Reasoning**: Configured with `LLM_TIMEOUT = 10.0s`.
- **Database Locks**: SQLite connections set `PRAGMA busy_timeout = 5000` (5 seconds).
- **Circuit Breaker**: `CircuitBreaker` trips on consecutive upstream timeouts or failures, failing fast rather than hanging threads.
- **Evaluation**: Timeouts are consistently configured across all external network and database operations.

### 2.12 Dependency Risks
- **Third-Party Libraries**: Minimal attack surface:
  - `fastapi` & `starlette` (Web framework)
  - `pydantic` (Data parsing and validation)
  - `httpx` (Async HTTP client)
  - `openai` (Optional LLM client)
  - `sqlite3` (Python standard library)
- **Zero Heavy Frameworks**: No ORMs with dynamic reflection or unvetted deserializers (e.g. no Pickle or YAML loaders).
- **Evaluation**: Low dependency risk footprint.

### 2.13 Database Consistency & Persistence
- **Relational Integrity**: SQLite foreign key constraints are enforced on every database connection via `PRAGMA foreign_keys = ON;`.
- **Concurrency**: WAL journal mode (`PRAGMA journal_mode = WAL;`) enables concurrent readers without locking out writers.
- **Migrations**: `schema_migrations` table records applied versions. Rejects databases with future/unsupported schema versions.
- **Transactions**: Explicit context manager (`get_db()`) commits on success and performs automatic `conn.rollback()` on exceptions.
- **Evaluation**: High integrity.

### 2.14 Analysis-Result Association
- **Scan Identifiers**: Each scan generates a unique random identifier: `scan_[a-f0-9]{16}`.
- **Cryptographic Provenance**: Computes `source_sha256` of submitted code and an `integrity_hash` over `(scan_id, source_sha256, verdict, evidence_trust, is_mock, created_at)`.
- **Evaluation**: High integrity and tamper detection.

### 2.15 Evidence-to-Finding Association
- **Foreign Keys**: `scan_evidence` and `scan_findings` reference `scans(scan_id) ON DELETE CASCADE`.
- **Candidate Linkage**: Fix proposals verify that `candidate_id` exists within the parent scan before saving.
- **Evaluation**: Evidence and findings are strongly coupled to their parent scan.

### 2.16 Duplicate or Partial Records
- **Partial Analysis**: In multi-file projects where one file has a syntax error, valid files are analyzed and reported; the report isolates broken files without terminating the entire project scan.
- **Transaction Atomicity**: Database insertions for scan summary, project files, evidence, and findings occur within a single SQLite transaction. If any insertion fails, the entire transaction rolls back, leaving no orphaned rows.
- **Repeated Requests**: Each analysis run generates an independent timestamped scan record; identical source codes can be queried via `source_sha256`.
- **Evaluation**: Predictable and consistent.

### 2.17 Retention and Deletion Behavior
- **Source Code Privacy**: User source code is **never** written to SQLite columns. Only `source_sha256` and `source_length` are retained.
- **Deletion Endpoint**: `DELETE /api/v1/scans/{scan_id}` validates ID format and executes `DELETE FROM scans WHERE scan_id = ?`.
- **Cascading Removal**: Because foreign keys are enabled, child records in `scan_evidence`, `scan_findings`, `scan_fix_proposals`, and `scan_project_files` are atomically removed.
- **Evaluation**: Clean deletion lifecycle; zero lingering data leaks.

---

## 3. Security Findings & Implemented Fixes

### Finding SEC-01: Unsanitized Virtual Filename Permitted Log Injection and Directory Traversal Representation
- **Severity**: Medium
- **Affected Component**: Single-file request schemas (`AnalysisRequest`, `AnalyzePythonRequest`, `IdentifyApiCallsRequest`, `ProposeFixRequest`).
- **Risk**:
  1. **Log Injection (CWE-117)**: Filenames containing newline (`\n`) or carriage return (`\r`) characters allowed forging fake log entries when logged via `logger.info("... %s", request.filename)`.
  2. **Path Traversal Representation**: Filenames containing `../../` were accepted into database records and analysis reports.
- **Reproduction Method**:
  ```python
  client.post("/api/v1/analyze", json={
      "source": "import stripe",
      "filename": "clean.py\n2026-10-21 [CRITICAL] Fake forged log line",
  })
  # Returned HTTP 200 and logged multi-line forged output.
  ```
- **Recommended Fix**: Add a centralized, strict `validate_safe_filename()` validator across all single-file schemas that:
  - Rejects NUL bytes (`\0`).
  - Rejects newlines (`\n`, `\r`).
  - Rejects directory traversal sequences (`..`).
  - Rejects absolute paths (leading `/` or `\\`) and drive letters (`C:`).
  - Enforces length <= 255.
  - Preserves legitimate relative subpaths (e.g. `services/payments.py`).
- **Implemented Fix**:
  - Implemented `validate_safe_filename()` in `app/schemas/ast_analysis.py`.
  - Added `@field_validator("filename")` to `AnalyzePythonRequest`, `IdentifyApiCallsRequest`, `AnalysisRequest`, and `ProposeFixRequest`.
- **Verification & Regression Test**:
  - Added `test_filename_validation_rejects_traversal_and_log_injection` in `backend/tests/test_security_audit.py`.
  - Verified rejection with HTTP 422:
    - Newline injection -> HTTP 422 (`Input validation failed: filename: Filename contains prohibited newline...`)
    - Path traversal -> HTTP 422 (`Input validation failed: filename: Path traversal component ('..') is prohibited...`)
    - NUL byte -> HTTP 422 (`Input validation failed: filename: Filename contains prohibited NUL character.`)
    - Valid relative paths -> HTTP 200.
- **Remaining Risk**: None for virtual filename inputs.

---

## 4. Test Verification Summary

The complete security and integrity test suite was executed against the hardened backend:

```bash
PYTHONPATH=backend ./.venv/bin/python -m pytest backend/tests/test_security_audit.py
```
**Results:** **23 passed**, 0 failed.

Verified test categories:
1. HTTP Security Headers (nosniff, DENY, strict-origin, CSP, Permissions-Policy).
2. Request Payload Size Limits & DoS Protection (HTTP 413 on oversized payloads).
3. Client Request Rate Limiting (HTTP 429 on exhaustion).
4. SSRF Destination Validation (rejection of localhost, private IPs, cloud metadata).
5. Safe Zero-Execution AST Parsing (no subprocess, eval, or exec).
6. Secret & Key Scrubbing in errors, logs, and prompt reasoning.
7. SQL Injection Immunity in repository filter queries.
8. Safe Filename Validation & Log Injection Immunity (SEC-01).
9. Source Code Privacy & Cascading Deletion Verification.

---

## 5. Review Scope & Known Limitations

While the backend architecture is defensively hardened against common web and API vulnerabilities, the following boundaries and limitations apply:

1. **Authentication & Multi-Tenancy**:
   - The current v0.1.0 prototype does not implement API token authentication or user tenant isolation on `/api/v1/*` routes.
   - Recommended for production deployment: Add Bearer token authentication (JWT / OAuth2) or deploy behind an authenticating API Gateway.
2. **In-Memory Rate Limiting**:
   - The rate limiter uses an in-memory sliding window. In a horizontally scaled multi-worker or multi-container environment, rate limiting state is not shared across processes. A distributed store (e.g. Redis) is recommended for multi-instance deployments.
3. **Static Analysis Boundaries**:
   - Static AST parsing evaluates code structure. It does not certify absence of runtime bugs, dynamic monkey-patching, or behavior executed through eval/reflection.
4. **Third-Party Documentation Trust**:
   - Contract verification is strictly as accurate as the official documentation retrieved from official sources. Contradictory, incomplete, or ambiguous documentation is flagged as `unable_to_verify` rather than certified clean.
