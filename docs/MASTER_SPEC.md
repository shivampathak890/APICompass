# APICompass v3 — Master Specification

## 1. Product Mission
APICompass verifies Python API usage against official documentation and supporting technical sources. It identifies potentially deprecated or unsupported calls, explains evidence-backed findings, validates quotations in code, proposes corrections where justified, and abstains when evidence is insufficient.

**Core Principle**: The model proposes; deterministic code decides which claims can be displayed as verified.

## 2. Core Guarantees & Constraints
- **Initial Supported Language**: Python
- **Initial API Ecosystem**: Stripe
- **Documentation Retrieval**: TinyFish via pluggable adapter
- **Zero Execution Rule**: Never execute submitted code (`exec`, `eval`, `subprocess`, dynamic `import` are strictly prohibited). Inspection is AST-only.
- **Quote Verification Rule**: Never treat an LLM-generated quotation as evidence until deterministic string-matching verifiers validate it against normalized source text.
- **No Hallucinated Findings**: Never present an unsupported finding as a verified fact.
- **No Fabricated Fixes or Sources**: Never fabricate a fix, source URL, benchmark result, or successful test.
- **Explicit Mock Mode**: Never silently substitute mock data for failed live retrieval. Clearly label mock data in API responses and frontend badges.
- **Strict Mock Quarantine**: Mock fixtures can never produce production verified `clean` or `issues_found` verdicts against user code.
- **Secret Hygiene**: Keep API keys in environment variables; never expose secrets in frontend bundles, logs, API responses, or source control.
- **Untrusted Input**: Treat retrieved documentation pages, code comments, snippets, and model outputs as untrusted data, never executable instructions.

## 3. Verdict Model
APICompass emits strictly defined overall scan verdicts:
- `clean`: The completed scan found no verified issues within its stated scope under live trust.
- `issues_found`: At least one verified issue was identified with verified quotation receipts.
- `unable_to_verify`: Required verification could not be completed adequately (e.g. retrieval failure, missing documentation, mock quarantine, or model claims failing deterministic verification).
- `partial`: Optional status for a scan that completed only a portion of its intended scope.

A `clean` result does not imply every possible bug or API misuse has been ruled out. It certifies only that the evaluated contracts found no verified violations within the analyzed scope.

## 4. Security Rules
- AST-only parsing using Python's standard `ast` module.
- Strict SSRF defense on all documentation retrieval: domain allowlist (`stripe.com`, `docs.stripe.com`, `github.com/stripe/stripe-python`), blocking loopback/private CIDR addresses, and inspecting redirect destinations before following.
- Content sanitization: strip executable scripts, comments, and dangerous HTML before normalization.
- Strict Pydantic schema validation on all inputs, configurations, and API outputs.
- Bounded retries, tight timeouts, and rate limiting on all external network requests.

## 5. Architecture Subsystems
- **Core Runtime & Shell**: Foundation, FastAPI backend with healthcheck, React+TypeScript+Tailwind frontend shell, mock mode indicator, pytest suite, and verified local startup.
- **Static Python AST Analysis**: Zero-execution extraction of imports, aliases, function/class definitions, parameters, call chains, keyword args, relevant literals, and heuristic candidate identification.
- **Official Documentation Retrieval**: TinyFish adapter, source registry, canonical Stripe domain allowlisting, SSRF defense, offline mock fixtures, and normalized evidence schemas.
- **Evidence Court & Deterministic Adjudication**: Exact & whitespace-normalized quote verifier, SHA-256 content hashes, API contract matcher, conservative adjudication precedence, strict mock quarantine, and unified analysis endpoint.
- **LLM-Assisted Candidate Reasoning**: Optional LLM reasoning, typed ProposedClaims, bounded prompts, prompt-injection defense, SSRF URL checks, deterministic evidence gate, mock quarantine preserved.
- **Evidence-Gated Fix Proposals & Safe Re-Verification**: Constrained deterministic patch generation, AST edit isolation verification, in-memory re-parsing, safe re-adjudication, mock quarantine preservation, and frontend diff viewer integration.
- **SQLite Audit Repository & History**: Configurable SQLite persistence, WAL mode, foreign keys, versioned migrations, zero raw source storage by default, SHA-256 fingerprinting, history API with bounded pagination & filters.
- **Monaco Editor & Real-Time SSE Streaming**: Monaco Python editor with AST diagnostics, SSE progress streaming with client disconnect defense (`POST /api/v1/analyze/stream`), and comprehensive browser E2E Playwright test coverage.

## 6. Static AST Extraction Scope & Limitations
- **Scope**: Extracts structural Python symbols (modules, aliases, functions, parameters, classes, calls, string literals) and heuristic candidates without code execution.
- **Distinction from Verification**: Static AST extraction produces **heuristic candidates** based strictly on code structure and naming conventions. It does **not** determine whether a method or parameter is supported or deprecated against official documentation.
- **Limitations**:
  - Dynamic attribute access (e.g. `getattr(obj, "create")`) cannot be resolved statically.
  - Runtime variable assignments and monkey-patching are intentionally not tracked.
  - Complex metaprogramming or dynamically generated classes are inspected as static syntax trees only.

## 7. Official Documentation Retrieval & Security Rules
- **Approved Sources**: Canonical domains restricted to `docs.stripe.com`, `stripe.com`, and `github.com/stripe/stripe-python`. Note: `api.stripe.com` is an API/dashboard service endpoint and is strictly prohibited from documentation retrieval.
- **SSRF Defenses**:
  - HTTPS only; embedded credentials strictly rejected.
  - Direct IP literals, localhost, loopback (`127.0.0.0/8`, `::1`), and private/link-local/multicast IP addresses prohibited.
  - Ports restricted to 443; lookalikes and homoglyphs blocked (exact host matching against approved allowlist).
  - Redirect destinations re-validated against allowlist and SSRF guards.
- **Data vs Instructions**: Retrieved documentation text is treated strictly as untrusted data, never as executable code or model instructions.

## 8. Evidence Court & Integrity Invariants
- **Deterministic Quote Verifier**: Exact substring matching and whitespace-normalized matching against raw retrieved text. Verifies quotations directly without allowing rewrite or fabrication.
- **SHA-256 Content Fingerprint**: Content hash computed over normalized excerpt text proves content identity, not publisher authenticity.
- **Strict Mock Quarantine**: Mock evidence (`is_mock: true`) is strictly quarantined. Offline mock fixtures can NEVER produce production `clean` or `issues_found` verdicts against user code; `verified_issues` is always empty under mock fixtures, yielding `unable_to_verify` with `MOCK_EVIDENCE_ONLY`.
- **Zero Client Trust Override**: Public HTTP API requests (`AnalysisRequest`) forbid client-controlled trust injection (`extra = "forbid"` rejects `test_trust_override` with HTTP 422). Evidence trust is strictly derived by backend retrieval services.
- **Conservative Abstention Precedence**:
  - A file with zero in-scope API candidates returns `unable_to_verify` with `NO_IN_SCOPE_CANDIDATES`, never `clean`.
  - An unsupported API ecosystem returns `unable_to_verify` with `UNSUPPORTED_ECOSYSTEM`, never `clean`.
  - Unrecognized dynamic calls return `unable_to_verify`, never `clean`.
  - Internal parsing/analysis failures return `unable_to_verify` with `ANALYSIS_FAILURE`, never `clean`.
  - `clean` is reserved exclusively for the case where in-scope calls were identified, complete live official documentation was retrieved, and the calls conformed to that documentation without any detected violation.
- **Mock vs Live Distinction**: Results explicitly record `is_mock: bool` and `provider: str`. Mock fixtures are never misrepresented as live data.

## 8b. Evidence Court & Deterministic Adjudication Semantics
- **Deterministic Quote Verification**:
  - Quotations must exist as exact or whitespace-normalized substrings within retrieved official documentation.
  - Cryptographic content hashes (SHA-256) track the exact documentation excerpt evaluated.
  - Quotations attributed to the wrong canonical URL or unapproved domain are rejected.
  - Never silently rewrites quotations or uses fuzzy similarity as proof of existence.
- **API Contract Matching**:
  - Correlates AST candidates with retrieved documentation evidence without false inference from omissions.
  - Undocumented methods or parameters omitted from incomplete excerpts lead to candidate abstention (`unresolved`), never false violation errors.
  - Multi-operation ambiguity is explicitly flagged and leads to abstention.
- **Conservative Precedence**:
  1. Syntax error -> `unable_to_verify`
  2. Mock quarantine -> `unable_to_verify` (with `MOCK_EVIDENCE_ONLY`)
  3. Verified issues -> `issues_found` (unresolved candidates remain preserved)
  4. Unresolved candidates -> `unable_to_verify`
  5. All candidates verified clean -> `clean`

## 9. LLM-Assisted Candidate Reasoning & Evidence Gating
- **Core Principle**: The model proposes; deterministic code decides which claims can be displayed as verified.
- **Optional & Degraded Operation**: The system operates fully when `LLM_PROVIDER=disabled` or when no API key is provided, falling back cleanly without raising server exceptions.
- **Structured Claim Extraction**: Model outputs are constrained by typed Pydantic schemas (`CandidateReasoning`, `ProposedClaim`, `LLMReasoningResponse`) defining explicit risk categories and confidence levels.
- **Server-Side Validation**:
  - Discard model reasoning referencing unknown or hallucinated candidate IDs.
  - Discard or sanitize referenced evidence IDs not present in retrieved evidence.
  - Untrusted model-suggested URLs are strictly validated against the documentation source registry and SSRF allowlist (`validate_destination_url`). Unapproved or private destinations are rejected.
- **Prompt Injection Defense**:
  - User source code is placed inside strict delimiter tags (`<UNTRUSTED_USER_CODE>`).
  - Documentation text is placed inside `<UNTRUSTED_DOC_CONTENT>` tags.
  - Model instructions strictly specify that instructions inside untrusted blocks MUST NOT be followed.
- **Input Bounding**: Source code input is capped at `LLM_MAX_CHARS` (default 8,000 characters) to prevent token exhaustion and prompt denial-of-service.
- **Unverified Display Guarantee**: All proposed claims are returned to the client as `AISuggestion` objects explicitly labeled `"AI suggestion — not verified"`. They NEVER elevate evidence trust, alter deterministic verdicts, or create verified issues without live official evidence corroboration.
- **Mock Quarantine Invariant**: Even when the LLM proposes an issue, if evidence retrieval operates under mock mode, the verdict strictly remains `unable_to_verify` with reason `MOCK_EVIDENCE_ONLY` and `verified_issues=[]`.

## 10. Fix Proposal Policy, Safe Re-Verification & Scope Boundaries

### 10.1 Core Principle & Architecture
- **Evidence-Gated Generation**: Fixes are never generated blindly or based on hallucinated patterns. A fix is proposed if and only if the candidate is authenticated against AST, verified under live official trust, supported by deterministic quote verification, and covered by a complete API contract match.
- **Server-Side Authoritative Recomputation**: Clients can never supply unverified analysis reports, spoof candidates, or inject fake evidence. The backend recomputes the analysis from source code authoritatively using registered services.
- **Zero Execution**: User code is never executed via `exec`, `eval`, dynamic imports, or subprocesses during fix generation or re-verification.
- **Zero Disk Overwrite**: The fix proposer is strictly an in-memory transformation engine. It never writes to, modifies, or deletes files on the host filesystem.

### 10.2 Distinct Verification States
APICompass strictly separates four distinct concepts to prevent misleading guarantees:
1. **Syntax Validation** (`syntax_valid: bool`):
   - Confirms that proposed code compiles to a valid Python AST without syntax errors.
   - *Guarantee*: The code is syntactically well-formed Python.
   - *Boundary*: Syntax validity does **not** imply API contract compliance, correct parameters, or runtime success.
2. **Evidence-Supported Proposal** (`status: FixProposalStatusType`):
   - Confirms that the proposed replacement is directly derived from official documentation contracts and verified quote receipts under live source trust.
   - *Boundary*: Proposing a fix does not certify that the entire enclosing application is bug-free.
3. **Static Re-Verification** (`reverification_status: ReverificationStatusType`):
   - Re-runs the full deterministic Evidence Court adjudication pipeline in-memory against the proposed source code.
   - Emits structured outcomes:
     - `verified_resolved`: Under live official trust, the re-adjudication pipeline reports zero remaining issues for the candidate.
     - `partially_resolved`: The primary violation was mitigated, but secondary warnings or unresolved aspects persist.
     - `concern_persists`: Re-adjudication detects that the violation or contract discrepancy remains unresolved.
     - `reverification_inconclusive`: Re-adjudication cannot complete with live trust (e.g. offline mock fixtures, incomplete docs, or abstention).
     - `syntax_invalid`: Proposed code failed AST syntax re-parsing.
     - `not_attempted`: Proposal was ineligible or abstained prior to re-adjudication.
4. **Runtime Correctness** (Explicitly Not Evaluated):
   - APICompass **never** asserts that proposed code executes without runtime exceptions in production environments, networks correctly with third-party servers, handles edge-case data payloads, or conforms to unspecified business logic.
   - All fix proposals include explicit caveats clarifying this limitation.

### 10.3 Eligibility & Abstention Conditions
The server evaluates fix eligibility through `evaluate_fix_eligibility` and abstains under the following deterministic conditions:
- `mock_evidence_only`: Strict mock quarantine rule. When documentation evidence is retrieved from offline mock fixtures (`is_mock=True`), fix generation is prohibited to prevent false production assurance. Returns `reverification_status="reverification_inconclusive"`.
- `insufficient_evidence`: The candidate lacks verified official quote receipts or the retrieved documentation contract is incomplete or ambiguous.
- `unsupported_candidate`: The candidate does not match supported deterministic migration patterns (e.g., currently supported: Stripe `Charge.create` with legacy `source` -> `PaymentIntent.create` with `payment_method`).
- `syntax_check_failed`: Proposed code fails static AST parsing.
- `proposal_invalid`: Generated code fails AST edit isolation or produces invalid structures.
- `reverification_inconclusive`: Re-adjudication cannot certify clean resolution under live trust.

### 10.4 Constrained Edit Generation & AST Isolation
- **Line-Bounded Edits**: Transformations are restricted to the specific lines spanning the authenticated candidate call expression.
- **AST Edit Isolation Verification (`_verify_edit_isolation`)**:
  - The AST of the proposed code is structurally compared against the original AST for all lines outside the target edit range.
  - Surrounding imports, function definitions, class structures, comments, and logic outside the target candidate must remain identical.
  - If any unintended mutation is detected outside the candidate boundaries, the proposal is immediately aborted with `status="proposal_invalid"`.
- **Standard Unified Diff**: Emits standard diff format (`--- original`, `+++ proposed`) generated via Python's built-in `difflib.unified_diff` with explicit line endings.

## 11. SQLite Audit Repository & History Invariants

### 11.1 Privacy Guarantee & Zero Raw Source Retention Policy
- **Default Privacy Rule**: Raw user source code is **never** stored in SQLite by default (`SOURCE_RETENTION_ENABLED=False`).
- **Deterministic Source Fingerprint**: The server independently calculates the SHA-256 cryptographic digest and byte length over the source text. Only `source_sha256` and `source_chars` are persisted in the `scans` table.
- **Data Protection**: This policy protects proprietary code, API secrets accidentally left in code snippets, and customer credentials from disk leakage.

### 11.2 Normalized Relational Schema & Integrity Invariants
- **Schema Normalization**: Scan audit data is partitioned into normalized relational tables:
  - `scans`: Primary audit record (scan ID, timestamp, verdict, engine version, ecosystem, package, filename, source fingerprint, mock flag, summary, checks JSON, record integrity hash).
  - `scan_evidence`: Retrieved documentation evidence linked via `scan_id` (evidence ID, source URL, canonical URL, provider, doc version, excerpt text, excerpt SHA-256, mock flag, trust level, retrieved timestamp).
  - `scan_findings`: Verified contract violations linked via `scan_id` (candidate ID, symbol name, violation code, message, source lines, quote receipts JSON, evidence link).
  - `scan_fix_proposals`: Generated fix proposals linked via `scan_id` (proposal ID, candidate ID, eligibility status, unified diff, reverification status, reverification summary).
- **Foreign Key Cascades**: Foreign key enforcement is mandatory (`PRAGMA foreign_keys = ON;`). Deleting a parent scan transactionally cascades to delete all child evidence, findings, and fix proposals.
- **Concurrency & WAL Mode**: Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and busy timeouts (`PRAGMA busy_timeout = 5000;`) are enforced on every database connection.
- **Exact Stored-Excerpt Hashing**: Evidence excerpt hashes are computed directly on the truncated excerpt text (`ev.content_excerpt[:4000]`), guaranteeing that recomputing `hashlib.sha256(content_excerpt.encode('utf-8')).hexdigest()` matches `content_sha256` exactly.
- **Deterministic Record Integrity Digest**: Each scan stores a cryptographic digest (`integrity_hash`) computed via `compute_record_integrity_hash` over deterministic JSON (`sort_keys=True, separators=(',', ':')`) covering:
  - Scan ID and created timestamp
  - Final verdict and executive summary
  - Target ecosystem and filename
  - Server-computed source SHA-256 and source length
  - Evidence trust level and mock boolean flag
  - Deterministically sorted checks performed
  - Deterministically sorted verified issues (candidate ID, line, violation type, quote hash)
  - Deterministically sorted evidence items (evidence ID, canonical URL, mock flag)
  - *Disclaimer & Scope*: Explicitly disclaimed as a deterministic audit digest over stored fields, not a digital signature or blockchain proof.
- **Server-Side Fix Linkage Validation**: `ScanRepository.link_fix_proposal` enforces valid proposal ID format (`^prop_[a-zA-Z0-9_\-]{8,64}$`), validates parent `scan_id` existence, and confirms `candidate_id` belongs to the scan's findings before insertion. No proposal marked "applied".

### 11.3 Versioned Database Migrations & Controlled Startup Failure
- **Migration Tracking**: Dedicated `schema_migrations` table tracks applied migration version, name, and timestamp.
- **Atomicity & Idempotence**: All migrations run inside transactional blocks using standard library DDL. Repeated initialization is safe and idempotent.
- **Future Version Guard**: If the database file has a migration version greater than the maximum supported by the current codebase, or if database initialization fails due to unwriteable paths, startup immediately halts with a clean `RuntimeError` in FastAPI lifespan to prevent data corruption or degraded operations.

### 11.4 Scan History REST API & Query Boundaries
- **History List (`GET /api/v1/scans`)**:
  - Bounded pagination: `limit` capped at 100 (default 20), `offset` $\ge 0$.
  - Exact parameterized filters: `verdict`, `ecosystem`, `is_mock`.
  - Deterministic sorting: `ORDER BY created_at DESC, scan_id DESC`.
  - Lightweight summary items: returns scan metadata, source fingerprint, and issue count without loading heavyweight excerpts.
- **Historical Snapshot Viewer (`GET /api/v1/scans/{scan_id}`)**:
  - Reconstructs complete historical audit report with `is_historical=True`.
  - Zero Re-Adjudication: Loading historical scans never triggers live doc retrieval or LLMs.
- **Cascade Deletion (`DELETE /api/v1/scans/{scan_id}`)**:
  - Transactionally removes the scan record and all cascaded children.
  - Returns 404 for unknown or already deleted scan IDs.
- **SQL Injection & Path Safety**:
  - 100% of SQL statements utilize parameterized queries (`?`).
  - No client-controlled file paths: database location is configured exclusively via server environment variables (`APICOMPASS_DB_PATH`).
  - Internal database exceptions are sanitized into standard HTTP 500 responses without exposing file paths or stack traces.

### 11.5 Operational & Backup Procedures
- **Path Configuration**: Controlled via `APICOMPASS_DB_PATH` (defaults to `data/apicompass.db`). Parent directories are automatically created if missing.
- **Backup Strategy**: Online SQLite backups can be performed safely via `VACUUM INTO 'backup_path.db'` or standard filesystem snapshots during application operation due to WAL mode.

## 12. Real-Time Streaming & End-to-End Testing

### 12.1 Streaming Event Protocol (`POST /api/v1/analyze/stream`)
- **Format**: Server-Sent Events (`text/event-stream`), UTF-8 encoded, separated by `\n\n`.
- **Payload Schema**: Strict `ScanProgressEvent` (`extra="forbid"`):
  - `event_id`: UUID4 unique identifier.
  - `timestamp`: UTC ISO-8601 string.
  - `stage`: Ordered `ScanStageType` enum value.
  - `message`: Human-readable truthful status message.
  - `progress_percent`: Monotonically non-decreasing float between 0.0 and 100.0.
  - `report`: Optional full `AnalysisReport` attached only to terminal stages (`completed`, `failed`).
  - `error_detail`: Optional error information on failure.
- **Client Disconnect Invariant**: The stream generator checks client connectivity before every yield via `raw_request.is_disconnected()`. If client disconnects, generator terminates immediately, cleaning up resources and preventing double writes.

### 12.2 Browser E2E Testing Invariants
- All browser interactions are verified via Playwright Chromium headless runner.
- Zero reliance on production or developer databases: uses isolated `data/test_e2e.db`.
- Tests must pass idempotently across repeated runs without state bleeding.


