# APICompass: Technical Judges & Architecture Q&A Guide

**Target Audience:** Hackathon Judges, Security Reviewers, Senior Architects  
**Scope:** Technical Invariants, Algorithm Details, Verification Proofs, and Architectural Boundaries  

---

### Q1: What specific problem does APICompass solve?
**Answer:**  
API integrations drift constantly. When third-party providers (such as Stripe) release new API versions, deprecate parameters, or enforce new required arguments, existing codebase calls break silently.  
- **Traditional static linters** (Flake8, Ruff) inspect syntax and style, but have zero awareness of upstream API documentation.
- **LLMs / AI assistants** hallucinate non-existent parameters, propose outdated methods, and provide confident but ungrounded explanations.  
APICompass bridges this gap by statically analyzing Python API usage against verified, official documentation contracts using deterministic exact-quote matching and cryptographic receipt verification.

---

### Q2: What does the backend actually analyze? Does it ever execute code?
**Answer:**  
The backend analyzes the Abstract Syntax Tree (AST) of the submitted Python code using Python's standard library `ast.parse()`.  
**Zero-Execution Invariant:** Source code is **never executed, evaluated (`eval`), run (`exec`), imported, or compiled to bytecode**. It is inspected purely as structured data. The AST visitor extracts:
- Module imports and aliases (`import stripe as st`, `from stripe import PaymentIntent`)
- Receiver variable tracking (`client = stripe.StripeClient(); client.charges.create(...)`)
- Method names, argument identifiers, keyword names, and positional argument indices
- Exact line numbers and column offsets for code coordinate mapping

---

### Q3: How are issues detected? What are the detection rules?
**Answer:**  
Issues are detected by the **Evidence Court** using deterministic contract matching rules:
1. `stripe_param_deprecated`: Parameter is present in code, but official docs state it is deprecated or superseded.
2. `stripe_param_missing_required`: An argument marked required in documentation is omitted in the call (unless dynamic `**kwargs` unpacking is detected).
3. `stripe_param_unsupported`: A parameter is passed that the official documentation explicitly flags as unsupported or invalid.
4. `stripe_op_deprecated`: The entire endpoint/method (e.g. `stripe.Token.create_card`) is marked deprecated in official documentation.
5. `stripe_constraint_violation`: A literal parameter violates explicit documentation constraints (e.g., negative integer passed to `amount`).

---

### Q4: How is documentation evidence retrieved?
**Answer:**  
Documentation is retrieved via the **TinyFish Documentation Adapter** (`backend/app/retrieval/`):
- **Live Mode:** Dispatches asynchronous HTTP calls to TinyFish Search to locate the relevant canonical documentation URL on `docs.stripe.com`, followed by TinyFish Fetch to extract clean markdown text.
- **SSRF Defense:** Only approved domains (`stripe.com`, `docs.stripe.com`, `github.com`) can be requested. Private IP addresses (`127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`) and non-HTTP protocols are blocked.
- **Mock Mode:** When `MOCK_MODE=true` (or when internet connectivity drops), the engine loads offline mock fixtures from `backend/app/fixtures/`, enabling 100% offline functionality.

---

### Q5: How is evidence validated and falsified?
**Answer:**  
Evidence is validated deterministically:
1. **Exact Substring Verification:** Every evidence claim must include an excerpt string. The Evidence Court verifies that the exact substring exists within the retrieved documentation document.
2. **Cryptographic Fingerprinting:** A SHA-256 hash is computed over the verified quote.
3. **Traceability:** The URL, SHA-256 hash, and exact line excerpt are bundled into an immutable `EvidenceReceipt`. If the quote cannot be verified verbatim in the retrieved document, the finding is discarded.

---

### Q6: What role does AI / LLM play? Can an LLM hallucinate a finding?
**Answer:**  
**No. An LLM can never hallucinate a verified finding or alter an adjudication verdict.**  
Our core invariant is: **"The model proposes; deterministic code decides which claims can be displayed as verified."**  
- In default and offline operation, the LLM is completely disabled (`LLM_PROVIDER=disabled`).
- When enabled, an LLM is used strictly as an **advisory assistant** in a separate UI tab to suggest potential documentation search queries or explain complex migration steps in natural language.
- All verdicts (`clean`, `issues_found`, `unable_to_verify`), findings, and fix proposals are generated and validated exclusively by deterministic Python AST logic.

---

### Q7: How are false positives handled?
**Answer:**  
APICompass adheres to **honest abstention**:
- **Non-API Code:** Functions containing no Stripe calls are classified as `unable_to_verify` (honest abstention), not falsely marked as broken or clean.
- **Dynamic Kwargs:** If a call uses `**kwargs` unpacking, the missing required parameter rule refrains from flagging an issue because parameters may exist inside the unpacked dictionary (`EVAL-25`).
- **Comments and String Literals:** The parser ignores API method names in docstrings or comments (`EVAL-23`).
- **Ambiguous Docs:** If retrieved documentation contains conflicting statements or lacks confidence, the Evidence Court abstains with `unable_to_verify` (`EVAL-11`).

---

### Q8: What happens when documentation is missing or retrieval fails?
**Answer:**  
The system degrades gracefully to `unable_to_verify` with trust status `untrusted_or_unavailable` (`EVAL-12`). It never fabricates an assumption or emits an ungrounded issue. The UI clearly explains to the developer that verification could not be completed due to missing documentation.

---

### Q9: Which automated tests have been executed?
**Answer:**  
Real execution counts on the `feature/verification-integrity` branch:
1. **Pytest Backend Suite:** **694 passed, 3 skipped** (live network smoke), 0 failed.
2. **Detection Rules Matrix:** **24 passed, 0 failed** covering positive, negative, edge-case, and invalid-input shapes.
3. **Security Audit Suite:** **23 passed, 0 failed** covering SSRF, directory traversal, CWE-117, and secret scrubbing.
4. **Playwright E2E Browser Specs:** **58 passed, 0 failed** across 7 test suites (primary journey, state handling, transparency, end-to-end, findings interface, project analysis, sse parser).
5. **Curated Evaluation Benchmark Suite:** **26/26 passed (100.0%)** with 1.0 precision, 1.0 recall, and 1.0 F1 score.

---

### Q10: How is security addressed (source privacy, SSRF, injection)?
**Answer:**  
- **Zero Raw Source Retention:** By default, `SOURCE_RETENTION_ENABLED=false`. Source code is parsed in-memory and never written to disk or the SQLite database. Only SHA-256 hashes and line metrics are persisted.
- **Safe Path Sanitization:** `validate_safe_filename()` blocks directory traversal (`..`), absolute paths, and CWE-117 newline log injections.
- **SSRF Defense:** External requests validate destination URLs against strict domain allowlists and reject private subnet IPs.
- **Secret Scrubbing:** Regex filters redact Stripe API keys (`sk_live_...`), OpenAI keys, and passwords before logging or database insertion.

---

### Q11: What limitations remain?
**Answer:**  
1. **Target Ecosystem:** Currently calibrated for the Stripe Python SDK ecosystem. Other SDKs (Boto3, Twilio) are planned next.
2. **Dynamic Metaprogramming:** Python code invoking APIs dynamically via `getattr(stripe, "Charge")()` cannot be resolved statically and produces honest abstention.
3. **Runtime Semantics:** Static analysis confirms syntax validity and contract compliance, but cannot test live network connectivity, webhook signature secrets, or banking fund authorizations.

---

### Q12: How could the system scale to large codebases?
**Answer:**  
1. **Parallel AST Worker Pool:** Parsing and AST visitor traversals are CPU-bound andembarrassingly parallel. A Celery/Redis or multiprocessing worker pool can distribute repository files across multiple cores.
2. **Document Embedding & Substring Cache:** Retrieved official documentation contracts are immutable per SDK version; caching extracted contracts in Redis reduces network overhead to near zero.
3. **Incremental Git Diffs:** In a CI/CD GitHub Action, APICompass only needs to inspect files modified in the pull request diff, completing analysis in under 2 seconds.

---

### Q13: What makes this approach superior to simpler alternatives (e.g. asking ChatGPT)?
**Answer:**  
1. **Zero Hallucination:** ChatGPT frequently guesses parameter names and quotes non-existent documentation. APICompass verifies exact quotes and computes cryptographic SHA-256 fingerprints.
2. **Audit Trail & Repeatability:** APICompass produces structured, verifiable audit snapshots in SQLite that can be archived for regulatory compliance.
3. **Deterministic CI/CD Integration:** LLMs produce non-deterministic outputs across runs; APICompass yields 100% consistent pass/fail verdicts on identical code.
