# APICompass — Hackathon Demonstration Runbook

**Target**: Hackathon Evaluators, Demonstrators & Pair Programmers  
**Application**: APICompass v3 (Python Static AST & Stripe API Contract Verifier)  
**Supported Scope**: Python (3.11–3.14) & Stripe API Ecosystem (`stripe`)

---

## 1. Executive Summary & Verification Architecture

APICompass is a zero-execution API contract verification engine. It evaluates user-submitted Python code against official documentation requirements without running, evaluating, or executing the source code.

```
Python Code Submission (AST Zero-Execution)
       │
       ▼
Stripe API Call Identification & Call Graph Extraction
       │
       ▼
Documentation Search & Fetch (TinyFish Live OR Controlled Mock Fixtures)
       │
       ▼
Deterministic Contract Matching & Quote Verification (SHA-256 Hashes)
       │
       ▼
Evidence Adjudication Court
 ├── Live Official Source ──> "issues_found" (Verified Issues) OR "clean" (No Issue Detected)
 ├── Mock Evidence Quarantine ──> "unable_to_verify" (Mock Quarantined — Unverified)
 └── Unresolved / Missing Docs ──> "unable_to_verify" (Explicit Abstention & Caveats)
```

### Core Principle
> **"The model proposes; deterministic code decides which claims can be displayed as verified."**

- **Live Mode**: Uses TinyFish Search & Fetch to retrieve live, current documentation from `docs.stripe.com`. Findings are verified deterministically against exact excerpts.
- **Offline Mock Mode**: Uses local deterministic fixtures. All findings are quarantined to `unable_to_verify` with visual `MOCK QUARANTINE (UNVERIFIED)` badges to guarantee that mock data never masquerades as live-verified production findings.

---

## 2. Environment Configuration Reference

Create your local `.env` from `.env.example`:

```bash
# Linux / macOS
cp .env.example .env

# Windows (PowerShell)
Copy-Item .env.example .env
```

### Configuration Variables

| Variable | Default Value | Purpose | Required for Live Demo? |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | `development` | Runtime mode (`development`, `testing`, `production`) | No |
| `MOCK_MODE` | `true` | `true` = deterministic local fixtures; `false` = live TinyFish calls | **Set to `false` for live demo** |
| `API_HOST` | `127.0.0.1` | Backend binding address | No |
| `API_PORT` | `8000` | Backend port | No |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed CORS origin (no wildcards allowed) | No |
| `APPROVED_DOC_HOSTS` | `stripe.com,docs.stripe.com,github.com` | SSRF destination allowlist | No |
| `TINYFISH_API_KEY` | *(empty)* | Official TinyFish API key for live search & fetch | **Yes, if `MOCK_MODE=false`** |
| `TINYFISH_SEARCH_BASE_URL` | `https://api.search.tinyfish.ai` | TinyFish Search endpoint | No |
| `TINYFISH_FETCH_BASE_URL` | `https://api.fetch.tinyfish.ai` | TinyFish Fetch endpoint | No |
| `DOC_RETRIEVAL_TIMEOUT_SECONDS` | `15.0` | Timeout per external retrieval request | No |
| `DOC_CIRCUIT_BREAKER_FAILURES` | `3` | Consecutive failures before opening circuit breaker | No |
| `LLM_PROVIDER` | `disabled` | AI reasoning provider (`disabled`, `mock`, `openai`) | No |
| `APICOMPASS_DB_PATH` | `data/apicompass.db` | Local SQLite audit database path | No |
| `SOURCE_RETENTION_ENABLED` | `false` | Privacy guard: submitted source code is never stored | No |

> [!IMPORTANT]
> **No Secrets in Source Control**: Never commit real API keys or `.env` files to git. `.gitignore` is strictly configured to ignore `.env`, `*.db`, and test artifacts.

---

## 3. Fresh Application Startup Instructions

### Step 1: Start Backend Server (Terminal 1)

**Linux / macOS (bash):**
```bash
# Ensure virtual environment dependencies are installed:
./.venv/bin/pip install -r backend/requirements.txt

# Start FastAPI backend with automatic reload:
./.venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

**Windows (PowerShell):**
```powershell
# Ensure virtual environment dependencies are installed:
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Start FastAPI backend with automatic reload:
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

*Expected Terminal 1 Output:*
```text
INFO:     Started server process
INFO:     Initializing APICompass v3 (0.1.0)
INFO:     Environment: development | Mock Mode: True (or False)
INFO:     Allowed CORS Origin: http://localhost:5173
INFO:     SQLite audit database initialized at: data/apicompass.db
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

### Step 2: Start Frontend Development Server (Terminal 2)

```bash
# From repository root:
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

*Expected Terminal 2 Output:*
```text
  VITE v5.4.11  ready in 250 ms

  ➜  Local:   http://127.0.0.1:5173/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

---

### Step 3: Verify Frontend-to-Backend Connectivity

1. Open your browser and navigate to **`http://localhost:5173`**.
2. Inspect the **Status Bar** in the bottom footer:
   - **Backend Status**: Must show **`Connected`** with a green badge.
   - **API URL**: Displays `http://127.0.0.1:8000`.
   - **Mode Badge**:
     - If `MOCK_MODE=true`: Shows **`Mock Mode Active`** (yellow badge with `"Offline Fixtures"` tooltip).
     - If `MOCK_MODE=false`: Shows **`Live Documentation Retrieval`** (green badge).
   - **TinyFish Provider Badge**:
     - `Disabled`: When in mock mode.
     - `Configured (Unverified Connectivity)`: When `TINYFISH_API_KEY` is provided.
     - `Missing Credentials`: When in live mode without a key.
     - `Unavailable (External Limitation)`: When upstream API is unreachable or circuit breaker is open.

---

## 4. Step-by-Step Demonstration Checklist

### Scenario A: Known Issue Supported by Documentation
**Goal**: Demonstrate reliable identification of a documented deprecated parameter and evidence-backed finding generation.

1. In the Monaco editor on the main screen, paste:
   ```python
   import stripe

   def process_customer_checkout(token: str, amount_cents: int):
       # Deprecated Stripe parameter: Charge with 'source'
       return stripe.Charge.create(
           amount=amount_cents,
           currency="usd",
           source=token,
           description="Demo transaction"
       )
   ```
2. Click **Start Analysis**.
3. **Observe the Findings**:
   - In **Live Mode**:
     - Finding Title: `Legacy Deprecated Parameter: Source Parameter Support`
     - Status Badge: **`VERIFIED`** (green badge with checkmark).
     - Impact: `Breaking API Deprecation`.
     - Location: Line 5, column 11 (`stripe.Charge.create(...)`).
     - Supporting Quote: Exact text from `https://docs.stripe.com/api/charges/create` explaining that `source` is deprecated in favor of PaymentIntents.
     - Source Link: Clickable HTTPS link to Stripe API reference.
   - In **Offline Mock Mode**:
     - Status Badge: **`MOCK QUARANTINE (UNVERIFIED)`** (amber badge).
     - Summary explains that mock evidence cannot verify production code.
     - Overall Verdict: `unable_to_verify` with `MOCK_EVIDENCE_ONLY` limitation.

---

### Scenario B: Valid Code Example
**Goal**: Demonstrate that valid code does not falsely generate warnings or errors.

1. Replace the editor text with:
   ```python
   import stripe

   def create_modern_payment(customer_id: str, amount_cents: int):
       # Modern, supported Stripe API call
       return stripe.PaymentIntent.create(
           amount=amount_cents,
           currency="usd",
           customer=customer_id,
           payment_method="pm_card_visa",
           confirm=True,
           automatic_payment_methods={"enabled": True}
       )
   ```
2. Click **Start Analysis**.
3. **Observe the Findings**:
   - Status Badge: **`NO ISSUE DETECTED`** (emerald badge).
   - Card Title: `API Call Conforms to Verified Contract Constraints`.
   - **Scope Limitation Notice**:
     > *"A 'no issue detected' status indicates strictly that supported static checks found no documented contract violations within the analyzed scope. It covers only the checks actually performed and does not guarantee runtime correctness, network reachability, valid credentials, or the absence of unrelated bugs."*
   - Actively Performed Checks: AST validation, call graph extraction, contract matching, quote verification.

---

### Scenario C: Ambiguous or Unsupported Example
**Goal**: Demonstrate responsible abstention when AST cannot resolve dynamic variables or when non-API code is analyzed.

#### Case C1: Ambiguous Dynamic Arguments
```python
import stripe

def dynamic_charge(kwargs_dict):
    # Dynamic runtime parameters cannot be determined statically
    return stripe.Charge.create(**kwargs_dict)
```
- **Outcome**: Verdict is `unable_to_verify`.
- **Finding Card**: Displays an **`UNVERIFIED SUGGESTION`** or limitation caveat explaining that `**kwargs` cannot be resolved statically.

#### Case C2: Unrelated Function with Misleading Name
```python
def create(amount: int):
    # Unrelated local function matching a Stripe method name
    return amount * 2

result = create(500)
```
- **Outcome**: Verdict is `unable_to_verify`.
- **Caveat**: `NO_IN_SCOPE_CANDIDATES: Static AST analysis identified no supported Stripe API calls to verify.`
- Prevents false-positive reports on unrelated code.

---

### Scenario D: Controlled Offline Mock Mode
**Goal**: Demonstrate reliable offline presentation when external internet or API access is not available.

1. Ensure `.env` has `MOCK_MODE=true`.
2. Notice the top header and footer status card explicitly show **`Mock Mode Active`**.
3. Paste any Stripe code (e.g., Scenario A).
4. **Observe the Integrity Guarantee**:
   - The system displays the candidate calls and matching excerpts from offline fixtures.
   - The findings are labeled **`MOCK QUARANTINE (UNVERIFIED)`**.
   - The final verdict is conservatively reported as **`unable_to_verify`**.
   - Shows that APICompass refuses to fake a successful live integration.

---

### Scenario E: Retrieval Failure & Recovery Procedures
**Goal**: Demonstrate resilience when TinyFish credentials are missing or when upstream services fail.

#### Case E1: Missing TinyFish Key in Live Mode
1. Set `MOCK_MODE=false` and leave `TINYFISH_API_KEY=""`.
2. Restart backend:
   - Footer Status Card shows: `TinyFish: Missing Credentials`.
3. Submit code:
   - Analysis executes AST parsing.
   - Retrieval reports `CREDENTIALS_MISSING`.
   - The candidate remains unresolved with an honest explanation:
     > *"TinyFish API key (TINYFISH_API_KEY) is not configured."*
   - Verdict is safely `unable_to_verify`.

#### Case E2: Upstream Service Failure or Timeout Recovery Procedure
If live TinyFish retrieval fails during the live demonstration (e.g. rate limit, Wi-Fi interruption, or 503 service outage):

1. **Immediate In-App Recovery**:
   - Toggle to offline mock mode by updating `.env`:
     ```env
     MOCK_MODE=true
     ```
   - Restart the backend (or use the frontend toggle if available).
2. **Transparent Explanation**:
   - Point to the Status Card showing `TinyFish: Unavailable (External Limitation)`.
   - Explain to evaluators:
     > *"APICompass detected that the external documentation retrieval service is currently unavailable. Rather than failing silently, crashing, or inventing unverified results, APICompass transitioned safely to unable_to_verify and quarantined the offline fallback."*

---

## 5. Transparency Statement: What Remains Unverified Without Live Credentials

If the hackathon presentation is performed without active, paid TinyFish or OpenAI API keys:

| Component | Status in Offline Demo | What Is Conclusively Verified | What Remains Unverified |
| :--- | :--- | :--- | :--- |
| **Python AST Analyzer** | **Fully Verified** | Static parsing, call extraction, coordinate mapping | Dynamic runtime introspection |
| **Contract Matcher** | **Fully Verified** | Exact parameter validation, required/unsupported rules | Untested third-party SDK versions |
| **Quote Verifier** | **Fully Verified** | Substring and whitespace matching, SHA-256 digests | Uncached live documentation pages |
| **Evidence Court** | **Fully Verified** | Precedence rules, mock quarantine, abstention logic | N/A (court is entirely deterministic) |
| **Live Web Scraping** | *Unverified (Offline)* | N/A | Real-time live crawling of `docs.stripe.com` |
| **Live AI Reasoning** | *Unverified (Offline)* | N/A | GPT-4o-mini live candidate reasoning |

---

## 6. Pre-Demonstration Verification Checklist

Run these commands before your live presentation to verify that the environment is completely healthy:

- [ ] **Run Full Test Suite**:
  ```bash
  .venv/bin/pytest backend/tests/ -q
  # Must report: 628 passed, 2 skipped, 0 failed
  ```
- [ ] **Verify Production Build**:
  ```bash
  npm --prefix frontend run build
  # Must report: ✓ built in ... with 0 errors
  ```
- [ ] **Run Demonstration Scenarios Script**:
  ```bash
  PYTHONPATH=backend .venv/bin/python scratch/test_demonstration_scenarios.py
  # Must report: All demonstration scenarios executed successfully!
  ```
- [ ] **Verify Git Cleanliness**:
  ```bash
  git status
  # Verify no uncommitted databases, secrets, or .env files exist.
  ```

---

*End of Demonstration Runbook.*
