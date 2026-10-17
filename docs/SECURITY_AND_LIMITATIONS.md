# APICompass v3 — Security, Privacy, and Trust Limitations

This document specifies the threat model, privacy safeguards, trust boundaries, and technical limitations of APICompass v3.

---

## 1. Zero-Execution Guarantee

APICompass analyzes Python source code **purely as passive textual and syntactic data**.
- All code inspection is executed using Python's standard library `ast.parse()`.
- The analyzer **never** invokes `exec()`, `eval()`, `compile(..., 'exec')`, `importlib`, or subprocesses on user-submitted code.
- Submitted code cannot trigger network requests, access filesystem paths, or run arbitrary instructions on the server.
- Prompt injection defense: User code submitted to LLM reasoning services is encapsulated within `<UNTRUSTED_USER_CODE>` delimiters, with explicit instructions commanding the model to treat the content solely as passive data and ignore embedded instructions, prompts, or format overrides.

---

## 2. Request and Project Boundaries

To defend against Denial of Service (DoS) and excessive memory allocation, strict boundaries are enforced at the API boundary:
- **Single-File Payload Limit:** Maximum 100 KB (102,400 bytes) of source text. Payloads exceeding this limit are rejected with `HTTP 422 Unprocessable Entity`.
- **Multi-File Project File Count:** Maximum 20 files per project request (`HTTP 422` if exceeded).
- **Multi-File Per-File Limit:** Maximum 100 KB per individual file (`HTTP 422` if exceeded).
- **Multi-File Total Size Limit:** Maximum 500 KB combined across all files in the project (`HTTP 422` if exceeded).
- **Path Sanitization:** File paths must be relative and $\le 255$ characters. Paths containing `..`, absolute indicators (`/`, `\`, `C:`), non-`.py` extensions, or NUL bytes (`\0`) are rejected immediately with `HTTP 422`.

---

## 3. Server-Side Request Forgery (SSRF) Defenses

Documentation retrieval interacts exclusively with approved official endpoints:
- **Approved Domain Allowlist:** Documentation retrieval is restricted to canonical hosts specified in `APPROVED_DOC_HOSTS` (`stripe.com`, `docs.stripe.com`, `github.com`). Lookalikes (e.g., `d0cs.stripe.com`, `docs-stripe.com`) and API management domains (`api.stripe.com`) are blocked.
- **Port Restriction:** Only HTTPS over port 443 is permitted. HTTP, arbitrary ports, and non-HTTPS schemes are rejected.
- **Private & Loopback IP Defense:** Target URLs are resolved prior to requests and checked against RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`), and AWS metadata (`169.254.169.254`).
- **Redirect Validation:** Any HTTP redirects encountered during retrieval are re-validated through the full SSRF defense filter before following.

---

## 4. Evidence Provenance and Quote Verification

APICompass does not rely on unverifiable summaries or generative hallucinations:
- **Deterministic Quote Matching:** Quotations must exist directly within officially retrieved documentation excerpts.
  - **Exact Substring Match:** Verifies identical character sequences.
  - **Whitespace-Normalized Match:** Verifies character sequences after standardizing consecutive whitespace and line breaks.
- **SHA-256 Excerpt Fingerprint:** Every retrieved evidence item is assigned a SHA-256 content digest. This fingerprint proves **content identity** across the evaluation pipeline; it does **not** prove publisher authenticity or serve as a digital signature.

---

## 5. Evidence Court Verdict Semantics

The Evidence Court operates under conservative adjudication rules and emits three possible verdicts:
1. `clean (no supported issues found)`:
   - Emitted **only** when in-scope API calls are detected, verified against complete live official documentation, and found to have zero contract violations.
   - A `clean` verdict indicates only that supported checks found no verified contract violations within the analyzed scope. It does **not** guarantee the complete absence of bugs, security vulnerabilities, or runtime logic defects.
2. `issues_found (evidence-supported)`:
   - Emitted when deterministic quote verification confirms that user code calls deprecated, invalid, or unsupported API patterns matching official documentation.
3. `unable_to_verify (abstained)`:
   - Emitted whenever evidence is insufficient, ambiguous, incomplete, or quarantined.
   - Non-API code or zero in-scope API candidates strictly produce `unable_to_verify` (`NO_IN_SCOPE_CANDIDATES`). Zero candidates cannot be certified as clean.
   - Offline mock fixtures strictly produce `unable_to_verify` (`MOCK_EVIDENCE_ONLY`).

---

## 6. Strict Mock Evidence Quarantine

Offline mock fixtures allow developers to test and run APICompass without external API credentials or internet access.
- Mock evidence is assigned `evidence_trust="mock_fixture"` and `is_mock=True`.
- Mock evidence is strictly quarantined: it **never** produces production verified `clean` or `issues_found` verdicts against user code.
- Mock fix proposals are marked `mock_evidence_only` with `reverification_status="reverification_inconclusive"`.

---

## 7. AI Advisory Separation ("The Model Proposes; Deterministic Code Decides")

LLM candidate reasoning is strictly auxiliary:
- All LLM suggestions are typed as `AISuggestion` and prominently labeled `"AI suggestion — not verified"`.
- LLM suggestions **never** create confirmed findings, elevate unverified claims, or independently alter Evidence Court verdicts.
- Only deterministic code matching verified official quotations can establish contract findings.
- Each AI suggestion explicitly discloses *"What Remains Unverified"* to ensure full transparency.

---

## 8. Fix Proposals and In-Memory Re-Verification

- **Zero Overwrite Guarantee:** Fix proposals generate in-memory unified diffs only. Local source files on disk are **never** automatically modified or overwritten.
- **AST Syntax Validity Caveat:** Safe re-verification confirms that proposed code parses into a valid Python AST (`syntax_valid=true`). Valid syntax confirms that code parses; it does **not** prove runtime correctness, functional equivalence, or bug freedom.
- **Context in Diffs:** Diffs contain surrounding lines as diff context. Users must review proposed changes in their application context before applying them manually.

---

## 9. SQLite Persistence, Source Privacy, and Storage Limitations

- **Raw Source Code Retention:** The raw submitted Python source code is **never** stored in the database. The SQLite schema (`scans` and `scan_project_files`) possesses no raw source column; only the authoritative SHA-256 fingerprint (`source_sha256`) and character/byte count are persisted.
- **Status of `SOURCE_RETENTION_ENABLED`:** While `SOURCE_RETENTION_ENABLED` is defined in configuration (defaulting strictly to `False`), raw source code retention is intentionally unsupported by the current relational database schema and repository logic. Enabling this flag does not persist raw source text.
- **Source Fragments in Stored Diffs:** When an evidence-gated fix proposal is generated and linked to a scan audit record, the standard unified diff is stored in the `scan_fix_proposals` table (`diff` column). Diffs inherently contain surrounding original code lines as context to allow valid patch reconstruction. Consequently, isolated fragments of the analyzed code surrounding targeted candidates are persisted in stored proposals.
- **Evidence Excerpts:** Retained evidence in `scan_evidence` consists exclusively of official documentation excerpts and their SHA-256 fingerprints, never user code.
- **Audit Integrity Fingerprint (SHA-256):** A deterministic JSON digest (`record_sha256`) is computed over canonical report data at save time.
  - **Integrity Bounds:** The stored hash protects against accidental local database corruption or unintentional record edits.
  - **Non-Tamper-Proof Disclosure:** A locally stored hash does **not** provide cryptographic digital signatures or blockchain-level tamper-proof immutability against an attacker with write access to both the SQLite database file and application host.
- **Database Deletion and WAL Behavior:** Executing `DELETE /api/v1/scans/{scan_id}` transactionally deletes the scan and cascades across child evidence, findings, and fix proposal records. However, SQLite operates in Write-Ahead Logging (WAL) mode; deleted database pages are marked as free space rather than cryptographically zeroized or shredded from physical disk media until overwritten or reclaimed via `VACUUM`.

---

## 10. External Provider Status & Fault Tolerance

- **Configured $\ne$ Healthy:** A provider status of `"configured"` indicates that non-empty credentials exist in the environment. It does **not** indicate that upstream connectivity is verified or that the credentials are valid.
- **Provider Outages are Not Code Bugs:** If documentation retrieval or LLM reasoning fails due to upstream outages, network timeouts, or rate limits, the failure is reported as an external limitation. It is **never** presented as an issue with the user's code.
- **Bounded Resilience:** Network requests to TinyFish use bounded retries (maximum 2 retries), exponential backoff with jitter (initial 50ms, ceiling 2s), and an in-memory circuit breaker (opens after 3 consecutive failures, 30s recovery period).
- **Opt-In Live Smoke Tests:** Live provider connectivity tests (`test_live_smoke.py`) are strictly opt-in and gated behind `APICOMPASS_LIVE_SMOKE_TESTS=1`. Normal test suites never execute live network requests or incur provider costs.
