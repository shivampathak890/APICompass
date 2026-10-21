# APICompass: Technical Demonstration Script (5–7 Minutes)

**Target Audience:** Hackathon Judges, Technical Leads, Senior Software Engineers  
**Presenter Roles:** Developer 1 (Backend Verification & Architecture) & Developer 2 (Frontend & UX)  
**Required Setup:** Backend running on port 8000 (`MOCK_MODE=true` for 100% network resilience); Frontend running on port 5173.  

---

## Demonstration Timeline Overview

| Section | Topic | Allocated Time | Presenter |
| :--- | :--- | :--- | :--- |
| **Section 1** | The Problem: API Drift, Silent Breakages & Hallucinating Linters | 0:00 – 1:00 (1 min) | Dev 1 |
| **Section 2** | Supported Example Input (Legacy Stripe Checkout) | 1:00 – 1:45 (45s) | Dev 2 |
| **Section 3** | Live Analysis Workflow & Real-Time SSE Pipeline | 1:45 – 2:45 (1 min) | Dev 2 |
| **Section 4** | Adjudicated Findings & Source Coordinate Precision | 2:45 – 3:45 (1 min) | Dev 1 |
| **Section 5** | Evidence Receipts, Exact Quotes & SHA-256 Fingerprints | 3:45 – 4:30 (45s) | Dev 1 |
| **Section 6** | Evidence Court Validation Semantics & Honest Abstention | 4:30 – 5:30 (1 min) | Dev 1 |
| **Section 7** | System Boundaries & Known Limitations | 5:30 – 6:15 (45s) | Dev 2 |
| **Section 8** | Next Steps, Extensibility & Q&A Transition | 6:15 – 7:00 (45s) | Dev 1 & Dev 2 |

---

## Detailed Section-by-Section Walkthrough

### SECTION 1: The Problem (1:00)
**Presenter (Dev 1):**
> *"Modern software relies heavily on third-party APIs like Stripe, Twilio, and AWS. However, APIs evolve constantly. When SDKs deprecate methods, change required parameters, or alter payload contracts, the breakage often remains undetected until production runtime crashes.*
>
> *Traditional static linters like Flake8 or Ruff only check syntax and PEP8 style—they know nothing about upstream API contracts. On the other hand, LLM coding assistants frequently hallucinate non-existent parameters or invent outdated arguments.*
>
> *APICompass solves this with a strict architectural axiom: **The model proposes; deterministic code decides which claims can be displayed as verified.** We combine passive Python AST inspection with deterministic documentation verification to eliminate hallucinations entirely."*

---

### SECTION 2: Supported Input (0:45)
**Presenter (Dev 2):**
> *(Screen displays browser at `http://localhost:5173` with Monaco Editor).*
> *"Here in the Verification Studio, we load our 'Charge (Legacy Source)' preset.*
>
> *(Point to code on screen):*
> ```python
> import stripe
> stripe.api_key = "sk_test_placeholder"
>
> def process_payment(amount_cents: int, token: str):
>     charge = stripe.Charge.create(
>         amount=amount_cents,
>         currency="usd",
>         source=token,
>         description="Software subscription charge"
>     )
>     return charge["id"]
> ```
> *Notice two key architectural aspects:*
> 1. *This code is analyzed purely as text data. It is **never executed**, never imported into the runtime, and no subprocess is spawned.*
> 2. *The call uses the legacy `stripe.Charge.create` endpoint with the deprecated `source` parameter."*

---

### SECTION 3: Live Analysis Workflow (1:00)
**Presenter (Dev 2):**
> *(Click "Verify with Evidence Court" button).*
> *"Notice the real-time Server-Sent Events (SSE) progress indicator at the top.*
>
> *Unlike slow polling, the backend streams each stage of analysis directly to the browser:*
> 1. **Accepted:** *Backend validates schemas, checks character bounds, and assigns an audit ID.*
> 2. **Static AST:** *The AST engine parses syntax and resolves the call graph without execution.*
> 3. **Doc Search & Fetch:** *The retrieval pipeline pulls official API documentation.*
> 4. **Evidence Court:** *Deterministic contract rules compare the code against retrieved documentation.*
> 5. **Persistence:** *Scan metadata is committed to our local SQLite audit database—guaranteeing zero retention of raw source code."*

---

### SECTION 4: Adjudicated Findings & Source Coordinates (1:00)
**Presenter (Dev 1):**
> *(Switch to the 'Candidate Assessments' and 'Fix Proposal' tabs).*
> *"The Evidence Court has adjudicated the call. It identified candidate `cand_001` with rule ID `stripe_param_deprecated`.*
>
> *Look at the coordinate accuracy: `Line 7, Column 5`. If we click on the issue, Monaco automatically highlights the exact line in the editor.*
>
> *Now examine the Fix Proposal tab. APICompass generated an in-memory unified diff migrating `stripe.Charge.create` to `stripe.PaymentIntent.create`, replacing `source` with `payment_method`. Notice our zero-overwrite guarantee: clicking 'Use Proposed Version' updates the Monaco editor buffer only—it never silently modifies files on disk."*

---

### SECTION 5: Evidence Receipts & Cryptographic Verification (0:45)
**Presenter (Dev 1):**
> *(Click on 'Evidence Receipts' tab).*
> *"In APICompass, no claim is ever presented without traceable proof. Under Evidence Receipts, we inspect the exact documentation evidence:*
> - **Source URL:** `https://docs.stripe.com/api/charges/create`
> - **Exact Verified Quote:** *'Use the Payment Intents API instead of the Charges API...'*
> - **Cryptographic Fingerprint:** *Every evidence receipt includes a SHA-256 hash computed over the verified quote. This ensures that findings cannot be forged, manipulated, or hallucinated by an AI layer."*

---

### SECTION 6: Validation Semantics & Honest Abstention (1:00)
**Presenter (Dev 1):**
> *"Now let's examine how APICompass handles uncertainty and offline operation.*
>
> *(Point to the amber 'MOCK FIXTURE QUARANTINE' badge).*
> *Notice this amber warning: we are currently running in offline mock mode. In APICompass, mock evidence is strictly quarantined. Even though the mock fixture contains the right answer, the system refuses to issue a false production 'Verified' badge. Instead, it honestly renders `UNABLE TO VERIFY (Mock Quarantined)`.*
>
> *(Load the 'Non-API (Abstain)' preset and click Verify).*
> *Now look at this mathematical Fibonacci function. Traditional AI tools often hallucinate security issues or fabricate warnings. APICompass recognizes that no Stripe API calls exist and abstains honestly with zero false alarms."*

---

### SECTION 7: System Boundaries & Limitations (0:45)
**Presenter (Dev 2):**
> *"We believe in engineering transparency regarding system boundaries:*
> 1. **Ecosystem Scope:** *Currently calibrated for the Stripe Python SDK. Additional ecosystems like AWS Boto3 and Twilio are planned for future releases.*
> 2. **Static vs Runtime:** *Static inspection proves contract compliance and syntax validity; it cannot test live API credentials, banking network authorizations, or webhooks.*
> 3. **Dynamic Metaprogramming:** *Calls constructed via dynamic reflection (`getattr()`) are flagged as statically indeterminate rather than guessed."*

---

### SECTION 8: Next Steps & Conclusion (0:45)
**Presenter (Dev 1 & Dev 2):**
> *"In summary, APICompass provides:*
> - *Deterministic contract verification backed by cryptographic receipts.*
> - *Complete zero-execution safety and zero raw source retention.*
> - *Verified by 694 backend tests, 58 browser E2E specs, and a 26-case curated benchmark suite with 100% precision and recall.*
>
> *Our next milestones include GitHub Action CI/CD integration and expanding multi-file symbol resolution across complex Django and FastAPI services.*
>
> *Thank you, and we welcome your questions!"*
