# APICompass: Developer & Contributor Guide

**Document Version:** 1.0.0  
**Target Audience:** Backend & Frontend Developers, QA Engineers, DevOps  
**System Requirements:** Linux / macOS / Windows WSL2, Python 3.11+, Node.js 18+, npm 9+  

---

## 1. Quickstart Development Setup

### 1.1 Prerequisites
Ensure the following tools are installed on your machine:
```bash
python3 --version  # Must be >= 3.11
node --version     # Must be >= 18.0.0
npm --version      # Must be >= 9.0.0
```

### 1.2 Virtual Environment & Backend Setup
```bash
# 1. Create a Python virtual environment in the repository root
python3 -m venv .venv

# 2. Activate the virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install backend dependencies in editable development mode
pip install --upgrade pip
pip install -r backend/requirements.txt
```

### 1.3 Frontend Setup
```bash
# Install frontend dependencies
npm --prefix frontend install
```

### 1.4 Environment File Setup
Copy the sample environment file to `.env`:
```bash
cp .env.example .env
```
Ensure the default variables are set for local offline development:
```ini
APP_ENV=development
MOCK_MODE=true
API_HOST=127.0.0.1
API_PORT=8000
FRONTEND_ORIGIN=http://localhost:5173
APPROVED_DOC_HOSTS=stripe.com,docs.stripe.com,github.com
APICOMPASS_DB_PATH=data/apicompass.db
SOURCE_RETENTION_ENABLED=false
LLM_PROVIDER=disabled
```

---

## 2. Running Local Development Servers

You can run backend and frontend independently in separate terminal windows:

### Terminal 1: Backend Server (FastAPI on Port 8000)
```bash
source .venv/bin/activate
./.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --app-dir backend --reload
```
Check health endpoint:
```bash
curl http://127.0.0.1:8000/api/v1/health
```
Expected output:
```json
{
  "status": "healthy",
  "service": "apicompass-api",
  "version": "0.1.0",
  "mock_mode": true,
  "database_status": "connected"
}
```

### Terminal 2: Frontend Server (Vite on Port 5173)
```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```
Open your browser at `http://localhost:5173`.

---

## 3. Running Automated Test Suites

### 3.1 Backend Pytest Suite
```bash
# Run all unit, security, and integration tests (excluding live network smoke tests)
./.venv/bin/pytest -m "not live_smoke" -q

# Run the dedicated detection rules matrix test suite
./.venv/bin/pytest backend/tests/test_detection_rules_matrix.py -v

# Run the security audit suite
./.venv/bin/pytest backend/tests/test_security_audit.py -v
```

### 3.2 Evaluation Benchmark Suite
```bash
# Run the 26-case curated evaluation suite
PYTHONPATH=backend ./.venv/bin/python -m evaluation.runner

# Run with JSON output
./.venv/bin/python .agents/skills/run-eval-suite/scripts/run_eval.py --json
```

### 3.3 Frontend Build & TypeScript Typecheck
```bash
# Compiles TypeScript and builds production bundles
npm --prefix frontend run build
```

### 3.4 Playwright Browser End-to-End Tests
Playwright starts its own ephemeral backend and frontend instances automatically using `data/test_e2e.db`:
```bash
# Run all Playwright E2E suites
npm --prefix frontend run test:e2e

# Run a specific spec suite
npm --prefix frontend run test:e2e -- e2e/primary_journey.spec.ts
npm --prefix frontend run test:e2e -- e2e/api_compass.spec.ts
npm --prefix frontend run test:e2e -- e2e/transparency.spec.ts
```

---

## 4. Running a Sample Analysis & Inspecting Output

### 4.1 Via Web UI (Verification Studio)
1. Open `http://localhost:5173` in your browser.
2. Under "Presets", click **"Charge (Legacy Source)"**.
3. Click **"Verify with Evidence Court"** (or press `Ctrl + Enter`).
4. Observe the real-time SSE progress bar advance through `Accepted` -> `Static AST` -> `Doc Search` -> `Evidence Court` -> `Persistence`.
5. Review the resulting **Evidence Court Verdict** card:
   - **Verdict:** `UNABLE TO VERIFY (MOCK FIXTURE QUARANTINE)` when `MOCK_MODE=true` (or `ISSUES FOUND` in live mode).
   - **Candidate Assessments:** Click tab to inspect candidate `cand_001` flagging rule `stripe_param_deprecated` at line 7, column 5.
   - **Evidence Receipts:** Click tab to inspect the exact quoted official documentation excerpt, canonical doc URL, and SHA-256 fingerprint.
   - **Fix Proposal:** Click tab to view the unified diff migrating `stripe.Charge.create` to `stripe.PaymentIntent.create`. Click "Use Proposed Version in Editor" to apply in-memory.

### 4.2 Via Backend REST API (`curl`)
You can submit code directly to the backend endpoint without opening a browser:

```bash
# Analyze a sample snippet using synchronous endpoint:
curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "payment.py",
    "source": "import stripe\ndef pay(tok, amt):\n    return stripe.Charge.create(amount=amt, currency=\"usd\", source=tok)",
    "force_mock": true
  }'
```

Expected JSON Response structure:
```json
{
  "scan_id": "scan_...",
  "filename": "payment.py",
  "verdict": "unable_to_verify",
  "evidence_trust": "mock_fixture",
  "is_mock": true,
  "summary": "...",
  "candidate_assessments": [
    {
      "candidate_id": "cand_001",
      "rule_id": "stripe_param_deprecated",
      "location": { "file_path": "payment.py", "start_line": 3, "start_column": 11 },
      "advisory_fix": "Replace stripe.Charge.create with stripe.PaymentIntent.create"
    }
  ],
  "evidence_receipts": [
    {
      "quote": "Use the Payment Intents API instead of the Charges API...",
      "source_url": "https://docs.stripe.com/api/charges/create",
      "excerpt_sha256": "..."
    }
  ]
}
```

---

## 5. Docker Container Deployment

If Docker and Docker Compose are installed:
```bash
# Build and run backend and frontend containers
docker compose up --build

# Backend will be available at http://localhost:8000
# Frontend will be available at http://localhost:5173
```

---

## 6. Troubleshooting Common Issues

| Issue | Symptom | Immediate Resolution |
| :--- | :--- | :--- |
| **Port Conflict** | `address already in use: 8000` or `5173` | Run `fuser -k 8000/tcp 5173/tcp` or specify custom ports via `--port`. |
| **Database Lock** | `sqlite3.OperationalError: database is locked` | Stale write-ahead log. Run: `rm -f data/apicompass.db-wal data/apicompass.db-shm`. |
| **Missing TinyFish Key in Live Mode** | Status says "Missing Credentials" | Set `MOCK_MODE=true` in `.env` for 100% offline development, or provide `TINYFISH_API_KEY`. |
| **Monaco Worker 404** | Code editor does not render | Run `npm --prefix frontend run build` and ensure Vite is running without caching issues. |

---

## 7. Coding Standards & Integrity Guidelines

1. **Passive Inspection Invariant:** Never introduce `eval()`, `exec()`, or dynamic imports when analyzing code.
2. **Path Sanitization:** Always use `validate_safe_filename()` on any client-supplied file path to prevent directory traversal and log injection.
3. **Mock Transparency:** If `MOCK_MODE=true`, mock fixtures must never produce verified production verdicts (`clean` or `issues_found`). They must be quarantined to `unable_to_verify`.
4. **Zero Source Retention:** Do not persist submitted source code to the SQLite database unless explicitly enabled by `SOURCE_RETENTION_ENABLED=true`.
