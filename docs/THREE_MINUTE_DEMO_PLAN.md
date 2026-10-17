# APICompass v3 — 3-Minute Live Demonstration Plan

**Target Audience**: Hackathon Judges, Evaluators, and Technical Reviewers  
**Target Duration**: 3 minutes (180 seconds)  
**Supported Scope**: Python (3.11–3.14) & Stripe API Ecosystem (`stripe`)  
**Core Invariant**: *"The model proposes; deterministic code decides which claims can be displayed as verified."*

---

## ⏱️ Timeline Overview

| Timestamp | Part | Topic / Action | Core Value Demonstrated |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:25** | Part 1 | The Problem & The Invariant | Why API drift and AI hallucinations break code |
| **0:25 – 0:40** | Part 2 | Application & Environment Launch | Clean UI, zero-setup, transparent health status |
| **0:40 – 1:15** | Parts 3–5 | Code Input & Verified Finding | Zero-execution AST analysis & verified documentation |
| **1:15 – 1:40** | Parts 6–7 | Source Evidence & Contract Mismatch | Traceable quote verification with SHA-256 integrity |
| **1:40 – 2:05** | Part 8 | Uncertainty Handling & Abstention | No false alarms on dynamic kwargs or non-API code |
| **2:05 – 2:35** | Part 9 | Evidence-Gated Fix Proposal & Diff | One-click fix application with in-memory re-verification |
| **2:35 – 3:00** | Part 10 | Technical Architecture & Modes | Model proposes, deterministic code decides; Live vs Mock |

---

## Part A: Timed Script (Second-by-Second)

### 0:00 – 0:25 (25s) | Part 1: The API Contract Problem & Core Invariant

- **Visual**: Show the browser open to `http://localhost:5173` with an empty Monaco code editor and the APICompass header visible.
- **Presenter Spoken Script**:
  > *"When developers integrate third-party APIs like Stripe, they face a silent killer: **API drift**. SDKs evolve, parameters get deprecated, and integrations break in production. Traditional linters only check syntax and style, while AI coding assistants frequently hallucinate non-existent arguments.  
  > We built **APICompass** on a strict invariant: **The model proposes; deterministic code decides.** APICompass parses Python code using zero-execution static AST analysis, pulls real documentation via TinyFish, and validates every claim against exact quotes with SHA-256 fingerprinting."*

---

### 0:25 – 0:40 (15s) | Part 2: Open the Application in Supported Configuration

- **Visual**: Point to the status card in the top-right / footer showing provider status:
  - If **Live Mode**: Green badge `Live Documentation Retrieval`, TinyFish `Connected`.
  - If **Offline Mock Mode**: Amber badge `Mock Mode Active (Offline Fixtures)`.
- **Presenter Spoken Script**:
  > *"APICompass is running locally on Python 3.14 and FastAPI with a React TypeScript frontend. Notice our status card: whether running live with TinyFish or 100% offline with quarantined fixtures, the system is fully transparent about its evidence trust before we even run a scan."*

---

### 0:40 – 1:15 (35s) | Parts 3, 4 & 5: Enter Python Example, Run Checker & Inspect Finding

- **Visual Action**: Paste **Demo Input 1** (Legacy Stripe snippet) into the Monaco editor:
  ```python
  import stripe

  def process_checkout(token: str, amount_cents: int):
      # Uses deprecated 'source' argument and legacy Charge endpoint
      return stripe.Charge.create(
          amount=amount_cents,
          currency="usd",
          source=token,
          description="Demo checkout"
      )
  ```
  Click the **"Start Analysis"** button.
- **Visual Progress**: The real-time Server-Sent Events (SSE) progress indicator advances through:
  `Parsing AST` ➔ `Identifying Calls` ➔ `Retrieving Documentation` ➔ `Adjudicating Evidence`.
- **Presenter Spoken Script**:
  > *"Here is a realistic Python function calling `stripe.Charge.create` with the legacy `source` argument. Let's analyze it. Notice our SSE stream: user code is never executed or imported. APICompass safely parses the AST as data, identifies the Stripe call, retrieves the official documentation, and enters our Deterministic Evidence Court."*
- **Visual Result**: Finding card appears:
  - **Live Mode**: Green badge **`VERIFIED`** | Title: `Legacy Deprecated Parameter: Source Parameter Support` | Line 5, Col 11.
  - **Mock Mode**: Amber badge **`MOCK QUARANTINE (UNVERIFIED)`** | Summary explaining offline fixture quarantine.

---

### 1:15 – 1:40 (25s) | Parts 6 & 7: Open Source Evidence & Contract Mismatch

- **Visual Action**: Click the finding card to expand the evidence drawer or card details. Click the **Source URL link** (`https://docs.stripe.com/api/charges/create`) and highlight the **Verified Quote block**.
- **Presenter Spoken Script**:
  > *"Unlike generative AI linters that produce opaque advice, APICompass gives you court-grade evidence. Look at this verified excerpt:  
  > **'The source parameter is deprecated. We recommend using the Payment Intents API...'**  
  > APICompass verified this quote using exact substring matching and computed a SHA-256 fingerprint against the retrieved markdown. If an AI or heuristic suggested an issue but couldn't substantiate it with an exact documentation quote, it would be discarded. The observed code used `source`, but the contract dictates migrating to `PaymentIntent`."*

---

### 1:40 – 2:05 (25s) | Part 8: Uncertainty Handling & Honest Abstention

- **Visual Action**: Replace the editor text with **Demo Input 2** (Dynamic runtime `**kwargs`):
  ```python
  import stripe

  def dynamic_charge(kwargs_dict):
      # Dynamic runtime parameters cannot be determined statically
      return stripe.Charge.create(**kwargs_dict)
  ```
  Click **"Start Analysis"**.
- **Visual Result**:
  - Overall Verdict: **`unable_to_verify`** (Amber badge).
  - Candidate status: `unresolved` with confidence `uncertain`.
  - Explanation: Explicitly states that runtime dictionary unpacking (`**kwargs`) cannot be resolved statically at compile-time.
- **Presenter Spoken Script**:
  > *"Now watch what happens when we introduce uncertainty. Here, parameters are passed via runtime dynamic `**kwargs`. Traditional tools either crash or hallucinate false warnings.  
  > APICompass knows its boundaries. It halts at the AST boundary and issues an honest verdict: `unable_to_verify`. It tells the developer: 'We identified a Stripe call, but runtime arguments cannot be determined statically.' Zero false alarms."*

---

### 2:05 – 2:35 (30s) | Part 9: Evidence-Gated Fix Proposal & Diff Application

- **Visual Action**: Paste **Demo Input 1** back in (or use undo), run analysis, and click **"Review Proposed Fix"** on the finding card.
- **Visual Details**:
  - Side-by-side or unified diff modal opens:
    ```diff
    - return stripe.Charge.create(
    + return stripe.PaymentIntent.create(
          amount=amount_cents,
          currency="usd",
    -     source=token,
    +     payment_method=token,
          description="Demo checkout"
      )
    ```
  - Re-verification badge: `verified_resolved` (Live) or `reverification_inconclusive` (Mock).
  - Click **"Apply Proposed Fix"**. The editor code instantly updates in-place.
  - Click **"Start Analysis"** on the updated code.
  - Verdict switches to **`clean`** (`NO ISSUE DETECTED` with emerald badge)!
- **Presenter Spoken Script**:
  > *"APICompass doesn't just diagnose; it fixes. But every fix is evidence-gated. The engine generated a deterministic diff migrating `Charge.create` to `PaymentIntent.create` and mapping `source` to `payment_method`.  
  > Crucially, the server re-verified this patch in memory before offering it to ensure it introduces zero syntax errors and genuinely resolves the contract violation. With one click, we apply the fix, re-run, and our code is clean."*

---

### 2:35 – 3:00 (25s) | Part 10: Technical Architecture, Modes & Conclusion

- **Visual Action**: Bring up the Architecture diagram or point to the footer audit ledger.
- **Presenter Spoken Script**:
  > *"To summarize the architecture:
  > 1. Zero-execution Python AST analysis ensures user code never executes.
  > 2. TinyFish Search and Fetch retrieve canonical official documentation behind SSRF guards.
  > 3. The Evidence Court guarantees no claim is verified without exact cryptographic quote proof.
  > 4. In our SQLite audit database, privacy is total: `SOURCE_RETENTION_ENABLED=false`—we store only SHA-256 hashes, never your raw code.
  > 
  > APICompass makes third-party API contracts verifiable, transparent, and trustworthy. Thank you!"*

---

## Part B: Exact Demo Inputs

### Demo Input 1: Deprecated Call with Evidence-Backed Fix (Primary)
```python
import stripe

def process_checkout(token: str, amount_cents: int):
    # Uses deprecated 'source' argument and legacy Charge endpoint
    return stripe.Charge.create(
        amount=amount_cents,
        currency="usd",
        source=token,
        description="Demo checkout"
    )
```

### Demo Input 2: Dynamic Variable / Uncertainty Handling (Abstention)
```python
import stripe

def dynamic_charge(kwargs_dict):
    # Dynamic runtime parameters cannot be determined statically
    return stripe.Charge.create(**kwargs_dict)
```

### Demo Input 3: Compliant Modern API Call (Clean Verification)
```python
import stripe

def create_modern_payment(customer_id: str, amount_cents: int):
    # Fully supported modern Stripe API contract
    return stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        customer=customer_id
    )
```

### Demo Input 4: Non-API Function (False Positive Immunity)
```python
class DatabaseRepository:
    def create(self, table: str, record_id: int):
        return {"table": table, "id": record_id}

db = DatabaseRepository()
db.create(table="users", record_id=42)
```

---

## Part C: Expected Outputs Supported by Actual Verification

### 1. In Live Mode (`MOCK_MODE=false`, valid `TINYFISH_API_KEY`)

| Input | Overall Verdict | Finding Status Badge | Evidence Source | Proposed Fix Outcome |
| :--- | :---: | :---: | :--- | :--- |
| **Input 1 (Legacy Charge)** | `issues_found` | `VERIFIED` (Green) | `https://docs.stripe.com/api/charges/create` | `proposal_type: verified_correction`<br/>`reverification: verified_resolved` |
| **Input 2 (Dynamic kwargs)** | `unable_to_verify` | `UNRESOLVED` (Amber) | None (Abstains) | None (`ineligible`) |
| **Input 3 (Modern Payment)** | `clean` | `NO ISSUE DETECTED` (Emerald) | Verified compliant | None needed |
| **Input 4 (Non-API create)** | `unable_to_verify` | No findings | `NO_IN_SCOPE_CANDIDATES` | None |

### 2. In Offline Mock Mode (`MOCK_MODE=true`, zero credentials)

| Input | Overall Verdict | Finding Status Badge | Evidence Source | Proposed Fix Outcome |
| :--- | :---: | :---: | :--- | :--- |
| **Input 1 (Legacy Charge)** | `unable_to_verify` | `MOCK QUARANTINE (UNVERIFIED)` (Amber) | Local mock fixture (Quarantined) | `proposal_type: suggested_patch`<br/>`reverification: reverification_inconclusive` |
| **Input 2 (Dynamic kwargs)** | `unable_to_verify` | `UNRESOLVED` (Amber) | Local mock fixture (Quarantined) | None (`ineligible`) |
| **Input 3 (Modern Payment)** | `unable_to_verify` | `MOCK QUARANTINE` | Local mock fixture (Quarantined) | None |

---

## Part D: Application Startup Commands

### Method 1: Local Development (FastAPI + Vite)

```bash
# Terminal 1: Backend API (runs on 127.0.0.1:8000)
./.venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Frontend UI (runs on http://localhost:5173)
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

### Method 2: Docker Compose (Single Command)

```bash
# Build and launch both services in background:
docker compose up --build -d

# Verify containers are healthy:
docker compose ps

# Access:
# Backend: http://localhost:8000 (OpenAPI docs at http://localhost:8000/docs)
# Frontend: http://localhost:5173
```

### Pre-Flight Readiness Verification
```bash
# Verify backend readiness & health:
curl -s http://127.0.0.1:8000/api/v1/health | jq .
```

---

## Part E: Fallback Plan if Network or TinyFish Fails

If venue Wi-Fi drops, upstream rate limits trigger, or `TINYFISH_API_KEY` is not present:

1. **Immediate In-App Toggle**:
   - In `.env`, ensure:
     ```env
     MOCK_MODE=true
     ```
   - Restart the backend, or reload the page.
2. **Presenter Explanation to Judges**:
   > *"Notice the amber badge in the header: APICompass has detected that we are running in offline mock mode.  
   > Watch how our Evidence Court responds: instead of pretending mock fixtures represent verified live truth, it automatically quarantines all findings with amber **`MOCK QUARANTINE (UNVERIFIED)`** badges and conservative `unable_to_verify` verdicts.  
   > This proves our architectural invariant: APICompass will never fabricate verification or hide external failures from the developer."*

---

## Part F: Technical Architecture Summary

```
[User Python Source]
         │ (Zero-Execution ast.parse — NO eval, NO exec, NO subprocess)
         ▼
[Identified Stripe API Calls]
         │
         ├────────────────────────┬────────────────────────┐
         ▼                        ▼                        ▼
[SSRF Destination Guard]   [TinyFish Search]      [TinyFish Fetch]
(docs.stripe.com allowlist)  (Candidate URLs)       (Scraped Markdown)
         │
         ▼
[Deterministic Contract Matcher] ──> Validates parameters, types & deprecations
         │
         ▼
[Deterministic Quote Verifier] ────> Verifies exact substrings & SHA-256 hashes
         │
         ▼
[Evidence Court] ──────────────────> Issues 'issues_found', 'clean', or 'unable_to_verify'
         │
         ▼
[Fix Proposer & In-Memory Re-verifier] ──> Generates safe AST diffs
         │
         ▼
[SQLite Audit Ledger] ─────────────> Stores only source SHA-256 (0 source code stored)
```

---

## Part G: Known Limitations to Disclose if Asked

If evaluators ask about edge cases or system boundaries:

1. **Dynamic Runtime Variables**: Calls like `stripe.Charge.create(**get_dynamic_dict())` cannot be statically evaluated. APICompass safely abstains with `unable_to_verify` rather than generating false alarms.
2. **Runtime Reflection / Monkey-Patching**: Runtime alterations to SDK methods cannot be discovered via static AST inspection.
3. **Ecosystem Scope**: The analyzer is currently specialized for Python 3.11–3.14 and the Stripe API ecosystem (`stripe.*`). Other languages and third-party APIs are cleanly categorized as out of scope.
4. **In-Memory Rate Limiting**: The current rate limiter runs in-process per backend instance. A Redis adapter would be attached for multi-node production deployment.
