# APICompass Pre-Demonstration Security Audit Report

**Date**: October 18, 2026  
**Target Application**: APICompass v3 (Python AST Analysis & Stripe API Contract Verifier)  
**Scope**: Frontend React UI, FastAPI Backend, TinyFish Web Retrieval Integration, LLM Reasoning Service, SQLite Persistence, and Deployment Configuration.  
**Security Status**: **HARDENED FOR DEMONSTRATION** (0 Known High/Critical Vulnerabilities Remaining; 21/21 Dedicated Security Tests Passing; 628/628 Full Test Suite Passing).

---

## 1. Executive Summary

A comprehensive pre-demonstration security audit of APICompass was conducted prior to its hackathon presentation. The evaluation focused on validating defenses against code execution, credential leakage, server-side request forgery (SSRF), untrusted documentation handling, prompt injection, resource exhaustion, and client-side vulnerabilities.

All critical attack vectors have been systematically evaluated and hardened with defense-in-depth controls. User code is strictly parsed via the Python Standard Library AST without execution; external network requests are restricted to validated documentation endpoints; secrets are scrubbed at the source before logging or error responses; request payload sizes and client rate limits are enforced at the ASGI middleware level; and frontend links are validated against dangerous URI schemes.

---

## 2. Threat Modeling & Security Invariants

APICompass operates under the following threat model and security invariants:

| Security Invariant | Requirement | Implementation Mechanism | Status |
| :--- | :--- | :--- | :--- |
| **Zero Code Execution** | User-submitted code must **never** be executed, compiled, or evaluated. | Standard Library `ast.parse` only; no `eval()`, `exec()`, or subprocess invocation. | **VERIFIED** |
| **SSRF Prevention** | External HTTP calls must never reach cloud metadata, private subnets, or non-approved domains. | `validate_destination_url` and `is_private_or_restricted_ip` domain/IP/port allowlisting. | **VERIFIED** |
| **Secret Confinement** | API keys and tokens must remain on the backend and never leak into logs, errors, or storage. | Multi-tier regex redaction (`secret_scrubber.py`) across exception handlers and DB models. | **VERIFIED** |
| **Resource Exhaustion Defense** | Maliciously large payloads or abusive burst traffic must not degrade service availability. | `MaxPayloadSizeMiddleware` (2MB limit) and `InMemoryRateLimiter` (120 req/min sliding window). | **VERIFIED** |
| **Untrusted Content Isolation** | Scraped web content must not execute in frontend or hijack LLM prompts. | Structured parsing, XML-bounded prompt encapsulation, React JSX escaping, and URI protocol whitelisting. | **VERIFIED** |
| **SQL Injection Immunity** | Scan history queries and filters must be immune to SQL injection. | Parameterized SQLite queries exclusively; no dynamic SQL string concatenation. | **VERIFIED** |

---

## 3. Vulnerability Findings & Implemented Hardening

### 3.1 Unsafe Code Execution (CRITICAL — Remediated)
- **Vulnerability Assessment**: Because APICompass inspects Python code, any attempt to evaluate imports, instantiate classes, or execute scripts would allow arbitrary remote code execution (RCE).
- **Codebase Evidence**: `backend/app/services/python_ast_analyzer.py` utilizes `ast.parse(source, filename=filename)`. AST nodes are traversed using `ast.NodeVisitor` (`StripeCallVisitor`).
- **Remediation & Hardening**: Confirmed that `subprocess`, `os.system`, `eval`, `exec`, and dynamic module loading are strictly absent. Added `test_ast_parser_never_executes_submitted_code` which verifies that malicious code with side-effects (`os.system("touch ...")`) executes zero disk or process operations.

### 3.2 Server-Side Request Forgery & Destination Whitelisting (HIGH — Remediated)
- **Vulnerability Assessment**: The TinyFish integration retrieves external web documentation. Unrestricted URL fetching could allow attackers to pivot into local microservices, Docker host networks, or cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
- **Remediation & Hardening**:
  - Implemented strict destination validation in `backend/app/services/documentation/security.py`:
    1. **Scheme Validation**: Only `https://` is permitted (`http://`, `file://`, `gopher://`, etc. are rejected).
    2. **Domain Allowlist**: Only approved documentation domains (`docs.stripe.com`, `stripe.com/docs`, `github.com/stripe/stripe-python`, `pypi.org/project/stripe`) are allowed. API/dashboard endpoints (`api.stripe.com`, `dashboard.stripe.com`) are explicitly blocked.
    3. **Port Enforcement**: Only standard HTTPS port 443 is permitted.
    4. **IP & Metadata Blocking**: Rejection of IPv4/IPv6 loopback (`127.0.0.1`, `::1`), private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and link-local cloud metadata (`169.254.169.254`).
    5. **Credential Neutralization**: URLs with embedded userinfo (`https://user:pass@...`) are rejected.
    6. **Redirect Verification**: All redirect hops in `HttpClient` are individually validated against SSRF rules before following.

### 3.3 Secret & API Key Exposure (HIGH — Remediated)
- **Vulnerability Assessment**: Users might submit code containing live or test API keys (`sk_live_...`, `sk_test_...`), which could appear in server logs, database scan history, error messages, or prompt context sent to external LLMs.
- **Remediation & Hardening**:
  - Enforced `scrub_secrets` in `backend/app/services/llm/secret_scrubber.py` covering:
    - Stripe Live and Restricted Secret Keys (`sk_live_...`, `rk_live_...`, `sk_test_...`, `rk_test_...`)
    - Bearer authorization headers and JWT patterns
    - Generic passwords and secret assignment tokens
  - Exception Handler Scrubbing (`backend/app/main.py`):
    - Standardized `http_exception_handler` and `validation_exception_handler` scrub all exception detail messages before returning JSON responses.
    - Explicitly registered both `StarletteHTTPException` and `FastAPIHTTPException` so that Pydantic validation errors and route-level HTTPExceptions cannot bypass secret sanitization.
  - Scan History Privacy: Confirmed `SOURCE_RETENTION_ENABLED = False` by default. Scans only persist SHA-256 fingerprints, line counts, and sanitized finding snippets; raw source code is never stored in SQLite.

### 3.4 Request Payload Size Limits & Denial of Service (MEDIUM — Remediated)
- **Vulnerability Assessment**: Malicious clients could send multi-megabyte payloads to exhaust backend memory and freeze AST parsing threads.
- **Remediation & Hardening**:
  - Added `MaxPayloadSizeMiddleware` to `backend/app/main.py`.
  - Rejects incoming POST/PUT/PATCH requests exceeding `settings.MAX_REQUEST_BODY_BYTES` (2 MB) with HTTP 413 `PAYLOAD_TOO_LARGE` prior to buffering request bodies in memory.
  - Multi-file endpoint enforces limits of 20 files max and 500 KB per individual file.

### 3.5 Client Request Rate Limiting & Abuse Controls (MEDIUM — Remediated)
- **Vulnerability Assessment**: Repeated automated calls could overwhelm backend compute, degrade response times, or exhaust third-party API quotas.
- **Remediation & Hardening**:
  - Implemented `InMemoryRateLimiter` with a thread-safe sliding-window algorithm (`RATE_LIMIT_PER_MINUTE = 120`).
  - Added `RateLimiterMiddleware` enforcing HTTP 429 `RATE_LIMITED` responses with `Retry-After`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining` headers.
  - Health check (`/api/v1/health`) and OpenAPI doc routes are exempt.
  - In automated test environments (`pytest`), loopback test clients are gracefully exempted unless testing rate limit enforcement explicitly.

### 3.6 Untrusted Documentation & Prompt Injection Defense (MEDIUM — Remediated)
- **Vulnerability Assessment**: External documentation pages fetched from third-party sites could theoretically contain malicious prompt injection instructions attempting to manipulate LLM reasoning.
- **Remediation & Hardening**:
  - Unstructured HTML is parsed to clean text before being passed to reasoning engines.
  - Prompts encapsulate documentation excerpts within explicit XML boundary tags (`<documentation_excerpt>...</documentation_excerpt>`) accompanied by strict system instructions forbidding the LLM from executing or following instructions embedded inside the documentation text.
  - Evidence Adjudication Court enforces deterministic verification: an LLM suggestion can **never** promote an issue to `verified_issue` without exact string match against an official, live documentation contract. Mock evidence is quarantined to `unable_to_verify`.

### 3.7 Cross-Origin Resource Sharing (CORS) & Security Headers (LOW — Remediated)
- **Vulnerability Assessment**: Missing security headers expose users to MIME-type sniffing, clickjacking, and cross-site embedding. Wildcard CORS allows untrusted websites to query local API endpoints.
- **Remediation & Hardening**:
  - Added `SecurityHeadersMiddleware` injecting:
    - `X-Content-Type-Options: nosniff`
    - `X-Frame-Options: DENY`
    - `Referrer-Policy: strict-origin-when-cross-origin`
    - `Permissions-Policy: geolocation=(), camera=(), microphone=()`
    - `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`
  - Configured explicit CORS allowed origins (`settings.FRONTEND_ORIGIN`, supporting `http://localhost:5173` and `http://127.0.0.1:5173` in development; wildcard `*` is disabled).

### 3.8 Frontend Link Protocol Neutralization (LOW — Remediated)
- **Vulnerability Assessment**: Finding cards render documentation source links (`sourceUrl`). If an unvalidated URL entered the pipeline, malicious schemes like `javascript:alert(1)` or `data:text/html,...` could cause DOM-based Cross-Site Scripting (XSS) when clicked.
- **Remediation & Hardening**:
  - Updated `frontend/src/components/FindingCard.tsx` with strict protocol verification:
    ```tsx
    const isSafeUrl = (url: string): boolean => {
      try {
        const parsed = new URL(url);
        return parsed.protocol === 'https:' || parsed.protocol === 'http:';
      } catch {
        return false;
      }
    };
    ```
  - Unsafe or non-HTTP(S) URLs are neutralized and rendered as inert plain-text badges with an untrusted indicator, preventing browser script execution.

---

## 4. Test Suite & Verification Results

A dedicated automated test suite (`backend/tests/test_security_audit.py`) was executed alongside the complete backend and frontend test suites.

### 4.1 Dedicated Security Test Suite (`test_security_audit.py`)
- **21 / 21 Tests Passed (100%)**:
  1. `test_security_headers_present_on_api_responses`: Verifies CSP, Frame-Options, nosniff, and Permissions-Policy.
  2. `test_oversized_payload_rejected_with_413`: Verifies HTTP 413 rejection when `Content-Length` exceeds 2 MB.
  3. `test_rate_limiter_blocks_abusive_client`: Verifies HTTP 429 and `Retry-After` header generation.
  4. 13x `test_ssrf_destination_validation_rejects_malicious_urls`: Parametrized testing blocking:
     - Cloud metadata: `169.254.169.254`, `metadata.google.internal`
     - Private subnets: `127.0.0.1`, `10.0.0.1`, `192.168.1.1`, `localhost`
     - Forbidden ports: `8000`, `5173`, `8443`
     - Embedded credentials: `https://admin:secret@...`
     - API service endpoints: `https://api.stripe.com/v1/charges`
     - Unapproved domains: `https://attacker-domain.com/docs`
     - Dangerous schemes: `javascript:alert(1)`, `data:text/html;base64,...`
  5. `test_ssrf_private_ip_detection`: Validates IPv4/IPv6 private IP detection.
  6. `test_ast_parser_never_executes_submitted_code`: Confirms malicious side-effects in Python code are zero-executed.
  7. `test_secret_scrubber_redacts_keys_and_tokens`: Verifies live Stripe keys, tokens, and credentials redaction.
  8. `test_error_handlers_never_leak_secrets`: Tests HTTP 400 and HTTP 422 exception response sanitization.
  9. `test_sql_injection_immunity_in_scan_repository`: Validates parameterized SQLite queries against SQL injection attacks.

### 4.2 Full Backend Regression Suite
- **Result**: `628 passed, 2 skipped, 0 failed in 33.95s` across 29 test files.

### 4.3 Frontend Build & Compilation
- **Result**: `npm --prefix frontend run build` completed cleanly with `0 errors`.

---

## 5. Deployment Configuration & Operational Controls

For demonstration and production environments, the following settings must be maintained:

| Configuration Setting | Recommended Value | Purpose |
| :--- | :--- | :--- |
| `APP_ENV` | `production` | Disables `/docs`, `/redoc`, and debug endpoints. |
| `RATE_LIMIT_ENABLED` | `true` | Enforces sliding-window rate limiting. |
| `RATE_LIMIT_PER_MINUTE` | `120` | Protects server resources from abuse. |
| `MAX_REQUEST_BODY_BYTES` | `2097152` (2 MB) | Prevents large-payload denial-of-service. |
| `SOURCE_RETENTION_ENABLED` | `false` | Ensures user code is never written to disk or database. |
| `FRONTEND_ORIGIN` | Explicit domain (e.g. `https://apicompass.example.com`) | Restricts CORS to the trusted UI domain. |
| `TINYFISH_API_KEY` | Backend environment variable only | Prevents client-side API key leakage. |

---

## 6. Remaining Risks & Recommended Future Mitigations

While APICompass has been thoroughly hardened for hackathon demonstration, no application is 100% secure. The following known limitations and operational risks should be noted for future production scaling:

1. **In-Memory Rate Limiting in Multi-Instance Deployments**:
   - *Current Behavior*: The sliding-window rate limiter stores request timestamps in Python process memory.
   - *Limitation*: If scaled horizontally across multiple worker containers or Uvicorn processes, rate limits will be tracked per-process rather than globally.
   - *Recommended Mitigation*: Migrate to a shared Redis-backed rate limiter for distributed production clusters.
2. **Reverse Proxy IP Spoofing**:
   - *Current Behavior*: The rate limiter inspects the `X-Forwarded-For` header.
   - *Limitation*: If deployed without a trusted reverse proxy (such as NGINX or Cloudflare) stripping untrusted upstream headers, an attacker could spoof `X-Forwarded-For`.
   - *Recommended Mitigation*: Configure reverse proxies to sanitize and append client IPs reliably.
3. **LLM Non-Determinism on Complex Code Context**:
   - *Current Behavior*: While the Evidence Court enforces exact quotation matching for verification, the optional AI reasoning layer provides natural-language suggestions.
   - *Limitation*: Sophisticated prompt injection attempts hidden in complex code comments could influence the style or wording of AI suggestions (though they cannot alter verified findings).
   - *Recommended Mitigation*: Run LLM inference inside sandboxed evaluation containers with strict JSON schema response mode constraints.
4. **Third-Party Dependency Vulnerabilities**:
   - *Current Behavior*: Standard third-party packages (`fastapi`, `httpx`, `pydantic`, `react`, `monaco-editor`) are used.
   - *Recommended Mitigation*: Integrate automated dependency vulnerability scanning (e.g., Dependabot, Snyk, or `pip-audit`) into the continuous integration pipeline.

---

## 7. Audit Sign-Off

The security hardening implemented for APICompass provides robust protection against code execution, credential disclosure, SSRF, prompt injection, and resource exhaustion. The application is in a stable, verified, and secure posture for hackathon demonstration.

