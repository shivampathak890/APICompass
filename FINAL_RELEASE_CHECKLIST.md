# APICompass: Pre-Demonstration & Final Release Checklist

**Release Target:** APICompass Prototype Release v0.1.0  
**Git Branch:** `feature/verification-integrity`  
**Evaluation Mode:** Production Mock Mode (`MOCK_MODE=true` for 100% offline resilience)  

---

## 1. Pre-Flight Verification Checklist

Run these steps in sequence prior to beginning a technical presentation or judge walkthrough:

- [x] **1. Clean Environment Verification**
  - Python virtualenv activated (`source .venv/bin/activate`).
  - Python version verified: 3.11+.
  - Node version verified: v18+.
- [x] **2. Environment Configuration Check (`.env`)**
  - `MOCK_MODE=true` confirmed in `.env` (guarantees zero external network dependencies).
  - `APICOMPASS_DB_PATH=data/apicompass.db` set.
  - `SOURCE_RETENTION_ENABLED=false` set.
- [x] **3. Automated Test Verification**
  - Run backend unit tests: `./.venv/bin/pytest -m "not live_smoke" -q` (694 passed).
  - Run benchmark evaluation: `PYTHONPATH=backend ./.venv/bin/python -m evaluation.runner` (26/26 passed).
  - Run frontend build check: `npm --prefix frontend run build` (0 TypeScript errors).
- [x] **4. Port Availability Check**
  - Ports 8000 (backend) and 5173 (frontend) verified clear (`fuser 8000/tcp 5173/tcp`).
- [x] **5. Backend Server Launch**
  - Command: `uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --app-dir backend`
  - Verify health endpoint: `curl -s http://127.0.0.1:8000/api/v1/health` returns status `healthy`.
- [x] **6. Frontend Server Launch**
  - Command: `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173`
  - Open `http://localhost:5173` in Google Chrome or Chromium.
- [x] **7. UI Warmup Run**
  - Click "Charge (Legacy Source)" preset in Verification Studio.
  - Click "Verify with Evidence Court".
  - Confirm SSE stages advance to 100% and Evidence Court Verdict renders.
  - Confirm Candidate Assessments and Fix Proposal tabs populate.

---

## 2. Failure Recovery Runbook

| Failure Symptom | Immediate Root Cause | Recovery Procedure |
| :--- | :--- | :--- |
| **Port 8000 or 5173 Address Already in Use** | An old backend or Vite process was left running in the background. | Run `fuser -k 8000/tcp 5173/tcp` or kill by PID: `kill -9 $(lsof -t -i:8000 -i:5173)`. Restart servers. |
| **Monaco Editor Fails to Mount (Blank Screen)** | Browser failed to load local Monaco web worker chunk. | Hard refresh browser tab: `Ctrl + Shift + R` (`Cmd + Shift + R` on Mac). Verify console shows zero network 404s. |
| **Database Locked (`sqlite3.OperationalError: database is locked`)** | Stale WAL lock files left from a previous interrupted process. | Remove stale lock files: `rm -f data/apicompass.db-wal data/apicompass.db-shm data/test_e2e.db*`. Restart backend. |
| **Streaming Interrupted / SSE Connection Lost** | Network hiccup or backend crashed on unexpected payload. | Check backend terminal for traceback. Re-click "Verify with Evidence Court" (retry logic is built-in). |
| **Fix Proposal Diff Doesn't Apply** | Monaco editor state was changed or cursor active in another window. | Click "Use Proposed Version in Editor" again. Notice banner confirms application. |

---

## 3. Feature Classification Breakdown

To preserve technical integrity, features are clearly classified as **Implemented**, **Mock/Demo**, or **Future Plan**:

### Implemented & Fully Verified
- Zero-Execution Static AST parsing of Python source code (`ast_engine.py`).
- Call graph resolution of imports, aliases, and receiver chains.
- Parameter extraction, positional-to-keyword mapping, and `**kwargs` awareness.
- 5 Core detection rules (missing param, unsupported param, deprecated param, deprecated op, constraint violation).
- WHATWG-compliant resilient SSE streaming pipeline (`sseParser.ts`).
- Monaco editor with syntax error decorations and line-jumping navigation.
- Evidence Receipts with exact quote verification and SHA-256 fingerprinting.
- In-memory fix proposal diff generator with AST syntax re-verification.
- SQLite audit persistence with zero raw source retention.
- Scan history view with read-only snapshot inspection and record deletion.

### Mock / Demo Features (Offline Isolation)
- Offline mock documentation fixtures for `stripe.Charge.create`, `stripe.PaymentIntent.create`, `stripe.Customer.create`, and `stripe.Refund.create`.
- Mock quarantine: amber warning badges and explicit `unable_to_verify` verdicts preventing mock data from being confused with live production verification.

### Future Plans (Post-Hackathon)
- Multi-language AST support (TypeScript, Go, Java SDKs).
- GitHub Action CI/CD integration with pull request comment diffs.
- Automated PR bot for auto-submitting backward-compatible patch branches.
