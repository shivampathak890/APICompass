# APICompass Scan History, Database Models, and Audit Records Audit

**Date:** October 18, 2026  
**Status:** Complete & Authoritative  
**Components Evaluated:** SQLite Schema Migrations (`app/db/migrations.py`), Connection Manager (`app/db/connection.py`), Scan Repository (`app/repositories/scan_repository.py`), History Endpoints (`app/api/v1/scans.py`), Secret Scrubber (`app/services/llm/secret_scrubber.py`).

---

## 1. Executive Summary

An exhaustive technical audit and hardening of APICompass's audit trail, database persistence, and scan history subsystem was conducted. 

Key results:
- **Zero Raw Source Code Persistence:** By default, submitted Python source code is **never** written to SQLite. Only a cryptographic SHA-256 fingerprint (`source_sha256`) and character count (`source_length`) are recorded.
- **Strict Secret Scrubbing Across All Records:** All persisted strings (summaries, abstention reasons, checks performed, limitations, filenames, excerpts, finding messages, AST details JSON, syntax errors, and fix proposal diffs) pass through `scrub_secrets()` prior to database insertion, redacting Stripe API keys (`sk_live_...`), JWTs, Bearer tokens, and secrets to `[REDACTED_API_KEY]`.
- **Fault-Tolerant Storage Non-Interference:** Database failures (e.g. SQLite disk lock, out-of-disk, read-only mode) never break primary analysis execution. The analysis result is delivered to the user with `persistence_status="failed"` rather than returning HTTP 500.
- **Graceful Handling of Corrupted Records:** Malformed JSON in `details_json`, `checks_performed`, or `limitations_and_caveats`, as well as invalid subtable records in `scan_evidence` or `scan_project_files`, are logged with warnings and safely filtered out rather than crashing queries.
- **Environment Isolation:** Unit and integration tests run against isolated temporary SQLite files (`tmp_path / "test_apicompass.db"`), guaranteeing that local developer or production databases (`data/apicompass.db`) and end-to-end test databases (`data/test_e2e.db`) are never mutated during test runs.

---

## 2. Determination Analysis (8 Core Invariants)

| Determination Point | Architectural Status & Audit Finding |
|---|---|
| **1. Which analysis data is stored?** | Stored tables: `scans` (scan metadata, verdict, engine version, summary, counts, trust flags, integrity hash), `scan_evidence` (URL provenance, canonical URL, provider, truncated excerpt $\le$ 4000 chars, trust state, mock flags), `scan_findings` (finding type, candidate ID, line, category, scrubbed explanation, scrubbed AST details), `scan_fix_proposals` (proposal ID, status, scrubbed unified diff, syntax validation, reverification status), and `scan_project_files` (file path, file SHA-256, length, parse status, candidates count, syntax error). |
| **2. Is submitted source code persisted?** | **No.** Raw source code is never stored in SQLite. Only `source_sha256` (SHA-256 hex digest) and `source_length` (integer character count) are saved. Bounded AST fragments and diffs are scrubbed of secrets. |
| **3. Is documentation evidence stored?** | **Yes.** Documented URL provenance, canonical links, retrieval providers (`tinyfish_live`, `tinyfish_mock`), retrieval timestamps, trust states (`official`, `mock_fixture`), and sanitized excerpts (clamped to 4000 characters) are preserved. |
| **4. Could secrets appear in stored code or logs?** | **Guaranteed No.** All text columns pass through `scrub_secrets()` prior to SQL persistence. Patterns matching API keys (`sk_live_[0-9a-zA-Z]{24,}`), JWTs, Bearer tokens, and private headers are replaced with `[REDACTED_API_KEY]`. Logs never print raw SQL parameters containing secret keys. |
| **5. How records are retrieved?** | Purely local parameterized SQL queries (`row_factory = sqlite3.Row`). Retrieval helper `ScanRepository.get_scan(scan_id)` operates strictly offline and **never** makes network calls, documentation fetches, or LLM reasoning invocations. Retrieved records are flagged `is_historical=True`. |
| **6. Are duplicate or incomplete records possible?** | **No.** Scans use unique UUID v4 primary keys (`scan_[a-f0-9]{16}`). ACID transaction blocks ensure that main scan records and all child records (`scan_evidence`, `scan_findings`, `scan_project_files`) are committed together. On any failure, `conn.rollback()` executes, preventing orphaned or incomplete records. Cascading deletes (`ON DELETE CASCADE`) are enforced via `PRAGMA foreign_keys = ON`. |
| **7. Do storage failures break analysis?** | **No.** In `api/v1/analyze.py`, `stream_adjudicator.py`, and `project_adjudicator.py`, `save_scan` and `save_project_scan` calls are wrapped in defensive `try...except Exception` handlers. If SQLite encounters an error, the error is logged and the report is delivered with `persistence_status="failed"`. |
| **8. Are test databases separated from dev data?** | **Yes.** Production/development uses `data/apicompass.db` (overrideable via `APICOMPASS_DB_PATH`). E2E Playwright tests use `data/test_e2e.db`. Pytest backend tests dynamically instantiate isolated temporary SQLite databases per test via `tmp_path`, cleaning them up after test execution. |

---

## 3. Database Schema and Model Specifications

### Table: `schema_migrations`
Tracks deterministic schema versions applied to the database.
```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

### Table: `scans`
Primary audit record for completed or abstained single-file and multi-file analyses.
```sql
CREATE TABLE scans (
    scan_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    verdict TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_length INTEGER NOT NULL,
    pipeline_version TEXT NOT NULL,
    evidence_trust TEXT NOT NULL,
    is_mock INTEGER NOT NULL,
    llm_reasoning_status TEXT NOT NULL,
    candidates_count INTEGER NOT NULL DEFAULT 0,
    issues_count INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    suggestions_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    abstention_reason TEXT,
    checks_performed TEXT NOT NULL,
    limitations_and_caveats TEXT NOT NULL,
    disclaimer TEXT NOT NULL,
    integrity_hash TEXT NOT NULL
);
```

### Table: `scan_evidence`
Traceable evidence receipts linking verified findings to official documentation sources.
```sql
CREATE TABLE scan_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    package TEXT,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    content_excerpt TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    is_mock INTEGER NOT NULL,
    source_trust TEXT NOT NULL,
    doc_version TEXT,
    content_sha256 TEXT,
    verdict_influence TEXT
);
```

### Table: `scan_findings`
Deterministic findings and advisory AI suggestions, separated strictly by `finding_type`.
```sql
CREATE TABLE scan_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    finding_type TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    category TEXT NOT NULL,
    source_line INTEGER,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL
);
```

### Table: `scan_fix_proposals`
Bounded unified diffs and reverification results for proposed code repairs.
```sql
CREATE TABLE scan_fix_proposals (
    proposal_id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    diff TEXT,
    syntax_valid INTEGER NOT NULL,
    reverification_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    explanation TEXT NOT NULL
);
```

### Table: `scan_project_files`
Per-file audit metadata for multi-file project analyses (Migration 002).
```sql
CREATE TABLE scan_project_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_length INTEGER NOT NULL,
    parse_status TEXT NOT NULL,
    candidates_count INTEGER NOT NULL DEFAULT 0,
    syntax_error TEXT
);
```

---

## 4. Migration Policy & Engine

APICompass utilizes a deterministic, forward-only schema migration system in `app/db/migrations.py`:
1. **Idempotence:** Every migration statement uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. Running migrations repeatedly on an existing database will not overwrite, drop, or alter existing records.
2. **Forward Version Enforcement:** If an APICompass instance encounters an SQLite database initialized by a newer future engine (`version > CURRENT_SCHEMA_VERSION`), it halts safely with a `MigrationError`:
   ```text
   Database schema version X is newer than supported engine version Y.
   Please update APICompass to safely interact with this audit database.
   ```
3. **Non-Destructive Guarantee:** Migrations never execute `DROP TABLE`, `TRUNCATE`, or destructive column drops. Existing historical scans and evidence are preserved across upgrades.

---

## 5. Retention and Deletion Behavior

1. **Source Code Retention Policy:**
   - **Default:** `SOURCE_RETENTION_ENABLED = False` (or omitted). Raw source code is discarded immediately following AST parsing and adjudication. Only the SHA-256 fingerprint is persisted.
   - HTTP clients cannot enable source code retention via request payload fields; unauthorized parameters are rejected by Pydantic's `extra="forbid"`.
2. **Explicit Scan Deletion:**
   - Endpoint: `DELETE /api/v1/scans/{scan_id}`
   - Due to SQLite `PRAGMA foreign_keys = ON` and `ON DELETE CASCADE`, deleting a scan automatically purges all corresponding child records in `scan_evidence`, `scan_findings`, `scan_fix_proposals`, and `scan_project_files`.
   - Returns HTTP 200 with deletion timestamp, or HTTP 404 if the scan does not exist.

---

## 6. Verification and Test Suites

The audit and persistence mechanisms are covered by two test suites totaling **63 test cases**:

1. **`backend/tests/test_scan_persistence.py` (55 tests):**
   - Tests 01–07: Database initialization, idempotent migrations, foreign key constraints, connection scoping, and controlled startup failures.
   - Tests 08–18: Single-file scan persistence, server-side fingerprinting, zero source storage, mock flag persistence, and transactional rollbacks.
   - Tests 19–31: History list pagination, verdict and ecosystem filtering, deterministic ordering, 404 handling, SQL injection resistance, and overlong field truncation.
   - Tests 32–40: Compatibility with primary analysis endpoints, fix proposal endpoints, SSRF guards, and error sanitation.
   - Tests 41–55: Row-by-row privacy inspection, audit integrity hash determinism, fix proposal linkage validation, and engine restart round-trips.

2. **`backend/tests/test_scan_history_audit.py` (8 tests):**
   - `test_secret_scrubbing_in_single_file_scan_records`: Proves `sk_live_...` and Bearer tokens are scrubbed from every table row in SQLite.
   - `test_secret_scrubbing_in_project_and_fix_proposal_records`: Proves multi-file project records and fix proposal diffs are scrubbed of secrets.
   - `test_source_code_is_not_stored_by_default`: Row-by-row inspection confirming raw source canaries do not exist in the database.
   - `test_get_scan_handles_corrupted_json_in_all_subtables`: Proves corrupted findings, evidence, project files, and malformed lists are safely skipped without 500 errors.
   - `test_list_scans_handles_corrupted_rows_gracefully`: Proves corrupted records in `scans` table do not prevent listing remaining valid scans.
   - `test_storage_failure_does_not_break_analysis_endpoint`: Proves SQLite write failures return HTTP 200 with `persistence_status="failed"`.
   - `test_sql_injection_attempts_in_filters_and_ids`: Proves parameterized SQL queries neutralize injection attacks in filters and path parameters.
   - `test_database_test_isolation_guarantee`: Proves test fixtures isolate database writes to temporary directories without mutating development data.
