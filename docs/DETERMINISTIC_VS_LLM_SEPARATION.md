# Deterministic Analysis vs. Optional LLM Separation Architecture

## 1. Executive Summary

APICompass enforces a strict architectural boundary between **deterministic code analysis** and **optional, advisory LLM reasoning**. 

### The Core Integrity Invariant:
> **"The Model Proposes; Deterministic Code Decides."**
> 
> An LLM is **never** the sole or authoritative source of a verified contract violation, clean certificate, or documentation match. Every verified finding must be grounded in parsed AST facts and corroborated by official documentation through deterministic quotation verification. If the LLM provider is disabled, unavailable, times out, or hallucinates, the deterministic analysis pipeline remains 100% functional, truthful, and secure.

---

## 2. Decision Responsibility Separation Matrix

| Pipeline Stage | Component | Deterministic / LLM | Mechanism & Security Controls |
| :--- | :--- | :--- | :--- |
| **AST Parsing** | `python_ast_analyzer.py` | **100% Deterministic** | Safe `ast.parse` with source size (<100 KB) and AST node count limits (<10,000 nodes). Zero code execution, zero imports of user code, zero `eval`. |
| **API Call Identification** | `python_ast_analyzer.py` | **100% Deterministic** | Explicit AST visitor mapping function/method calls to `ApiCandidate` objects with receiver, target method, arguments, and line/col locations. Ambiguous patterns preserve uncertainty (`is_ambiguous=True`). |
| **Secret Scrubbing & Code Isolation** | `secret_scrubber.py` | **100% Deterministic** | Regex redaction of Stripe live/test keys, webhook secrets, restricted keys, and passwords. Bounded extraction of candidate windows (context = 2 lines) with unrelated business logic omitted (`# ... [unrelated code omitted] ...`). |
| **Input Sanitization & Injection Defense** | `secret_scrubber.py` | **100% Deterministic** | Neutralizes XML delimiters (`<system>`, `</system>`, `<prompt>`, `</UNTRUSTED_CODE_FRAGMENTS>`, `<|im_start|>`) to prevent untrusted user code or docs from breaking delimiter boundaries. |
| **Doc Domain Validation & SSRF Defense** | `security.py` | **100% Deterministic** | Resolves DNS and blocks loopback (127.0.0.0/8), private subnets (RFC 1918, RFC 4193), AWS/GCP cloud metadata (`169.254.169.254`), non-HTTPS protocols, and unallowed domains (only `stripe.com` allowed). |
| **Documentation Resolution** | `registry.py` & `retrieval_service.py` | **100% Deterministic** | Priority-ordered: (1) Registry fast path for canonical Stripe endpoints, (2) Deterministic TinyFish Search, (3) Safe Fetch. Relevance scoring rejects disjoint API documentation. |
| **Contract Extraction** | `contract_extractor.py` | **100% Deterministic** | Structured parser extracting parameter tables, required flags, type constraints, and deprecation notices from official HTML/Markdown. |
| **Contract Comparison** | `contract_matcher.py` | **100% Deterministic** | Compares AST candidate arguments against extracted contract constraints. Checks missing required parameters, deprecated parameters, deprecated operations, and literal constraint violations. |
| **Quotation Verification** | `quote_verifier.py` | **100% Deterministic** | Verifies claimed quotes against SHA-256 digested documentation excerpts using exact substring or whitespace-normalized matching. Distinguishes exact quotations from paraphrases. |
| **Adjudication & Verdict Assignment** | `adjudicator.py`, `stream_adjudicator.py` | **100% Deterministic** | Conservative precedence: (1) Syntax Error -> `unable_to_verify`, (2) Zero candidates -> `clean` (with in-scope caveat), (3) Mock evidence -> `unable_to_verify` (mock quarantine), (4) Verified issue -> `issues_found`, (5) Ambiguous/missing docs -> `unable_to_verify`, (6) Complete contract + zero violations -> `clean`. |
| **Candidate Interpretation & Explanations** | `provider.py`, `mock_provider.py` | **Optional / Advisory LLM** | Generates natural-language summaries, contextual interpretation of the call, and advisory hypotheses. Model outputs are validated against strict Pydantic schemas. |
| **AI Hypothesis Quarantining** | `reasoning_service.py` | **100% Deterministic** | Discards hallucinated candidate IDs. Forces `verification_status="unverified_suggestion"` and `label="AI suggestion — not verified"`. Cannot promote suggestions to `verified_issues`. |

---

## 3. Strict Boundary Rules

### 1. Zero Direct Promotion
LLM proposed claims (`ProposedClaim`) are surfaced strictly in `ai_suggestions` within `AnalysisReport`. Under no condition can an LLM suggestion be added to `verified_issues`. Promotion to `verified_issues` requires that the issue originated from `contract_matcher.py` and passed exact quotation verification in `quote_verifier.py` against live official evidence (`source_trust == "official"`).

### 2. Secret Redaction & Code Boundedness
To avoid sending sensitive enterprise logic or secrets to third-party LLM providers:
- `extract_relevant_code_fragments`: Only extracts the top-level import statements and a 2-line window around recognized API call candidates. All intermediate functions, proprietary algorithms, and sensitive routines are stripped and replaced with `# ... [unrelated code omitted] ...`.
- `scrub_secrets`: Hardcoded Stripe secret keys (`sk_live_...`, `sk_test_...`), restricted keys (`rk_live_...`), webhook secrets (`whsec_...`), bearer tokens, and generic credentials (`password = "..."`) are redacted to tokens like `[REDACTED_STRIPE_LIVE_KEY]`.
- All untrusted text is wrapped in `<UNTRUSTED_CODE_FRAGMENTS>` tags, and prompt injection attempts inside comments or strings are neutralized.

### 3. Graceful Provider Failure & Fallback
The analysis pipeline wraps LLM calls in comprehensive error handlers:
- **`LLM_PROVIDER="disabled"` (Default)**: Immediately skips model invocations. AST analysis, documentation retrieval, contract matching, and verdict generation run with zero latency and zero external dependencies.
- **`AuthenticationError` (Invalid API key)**: Logged without leaking keys; returns `status="unavailable"`.
- **`RateLimitError` (HTTP 429)**: Returns `status="unavailable"` with clear user caveat.
- **`APITimeoutError` (Request timed out)**: Returns `status="unavailable"` without hanging the analysis.
- **`APIStatusError` (HTTP 500/502/503)**: Returns `status="error"`.
- **Malformed JSON or Schema Mismatch**: Caught and converted to `status="error"` with clear error description.
- In all failure modes, the core deterministic report is produced truthfully.

---

## 4. Verification Evidence

The separation architecture is verified by the automated test suite:
- **`backend/tests/test_llm_reasoning_audit.py`**: 14 tests verifying secret scrubbing, bounded code extraction, prompt injection neutralization, schema validation, timeout/auth/quota error handling, candidate ID authenticity enforcement, and quarantine invariants.
- **`backend/tests/test_llm_reasoning.py`**: 25 tests verifying provider integration, public HTTP endpoints, quote fabrication rejection, and URL allowlist enforcement.
- **Complete Test Suite**: All 529 non-smoke tests pass (`pytest -m "not live_smoke"`).
