# APICompass v3 — Setup, Operation & Developer Guide

This guide provides complete, beginner-friendly instructions for installing, configuring, running, and verifying APICompass v3 across Linux, macOS, and Windows.

> **Demonstrating the Application?** See the step-by-step **[Hackathon Demonstration Runbook](DEMONSTRATION_RUNBOOK.md)** for a live vs offline checklist, scenario walkthroughs, and failure recovery.
>
> **Prefer Docker?** See the **[Docker & Containerization Guide](DOCKER.md)** for single-command stack orchestration (`docker compose up --build -d`).

---

## 1. Prerequisites & Supported Versions

Ensure the following tools are installed on your system:
- **Operating System:** Linux, macOS, or Windows 10/11 (64-bit)
- **Shell:** bash, zsh, or PowerShell
- **Python:** Python 3.11, 3.12, 3.13, or 3.14
- **Node.js:** Node.js 18.x, 20.x, or 22+
- **npm:** npm 9+
- **Git:** Git 2.30+

Verify your prerequisites:
```bash
python3 --version   # or python --version
node --version
npm --version
```

---

## 2. Installation & Setup

### Step A: Backend Environment Setup

**Linux / macOS (bash):**
```bash
# 1. Create a Python virtual environment
python3 -m venv .venv

# 2. Upgrade pip in the virtual environment
./.venv/bin/pip install --upgrade pip

# 3. Install backend dependencies (core runtime and test suite)
./.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

**Windows (PowerShell):**
```powershell
# 1. Create a Python virtual environment
python -m venv .venv

# 2. Upgrade pip in the virtual environment
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# 3. Install backend dependencies (core runtime and test suite)
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt
```

### Step B: Frontend Environment Setup

Navigate to the `frontend` directory and install exact dependencies:

**Linux / macOS / Windows:**
```bash
cd frontend
npm ci
```

### Step C: Environment Configuration

In the repository root, create your local configuration from `.env.example`:

**Linux / macOS (bash):**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

The default settings in `.env.example` configure **offline mock mode** (`MOCK_MODE=true`, `LLM_PROVIDER=disabled`). No external paid API keys or live network access are required to run the full application or execute tests.

---

## 3. Running Development Servers

### Terminal 1: Start Backend Server

From the repository root:

**Linux / macOS (bash):**
```bash
./.venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --reload
```
The backend initializes the SQLite database at `data/apicompass.db` and listens at `http://127.0.0.1:8000`.

### Terminal 2: Start Frontend Development Server

From the `frontend` directory:
```bash
npm run dev -- --host 127.0.0.1 --port 5173
```
The frontend UI is available in your browser at `http://localhost:5173`.

---

## 4. Confirming Health & Running Verification

Open **Terminal 3** (PowerShell) to test the running system:

### 1. Confirm Backend Health
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" | ConvertTo-Json -Depth 4
```
Expected response:
```json
{
  "status": "healthy",
  "service": "apicompass-api",
  "version": "0.1.0",
  "mock_mode": true,
  "database_status": "ok",
  "provider_status": {
    "tinyfish": "disabled",
    "llm": "disabled"
  }
}
```

### 2. Run Single-File AST Analysis (Zero-Execution)
```powershell
$body = @{
    source = "import stripe`ncharge = stripe.Charge.create(amount=2000, currency='usd', source='tok_123')"
    filename = "payment.py"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/analyze/python" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 4
```

### 3. Run Unified Evidence Court Adjudication
```powershell
$body = @{
    source = "import stripe`ncharge = stripe.Charge.create(amount=2000, currency='usd', source='tok_123')"
    filename = "payment.py"
    ecosystem = "stripe"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/analyze" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 4
```

### 4. Run Multi-File Project Analysis
```powershell
$projectBody = @{
    project_name = "checkout_service"
    ecosystem = "stripe"
    files = @(
        @{
            path = "main.py"
            content = "from services.payment import process_order`ndef handle_checkout(): return process_order(1000, 'tok_visa')"
        },
        @{
            path = "services/payment.py"
            content = "import stripe`ndef process_order(amount, token):`n    return stripe.Charge.create(amount=amount, source=token)"
        }
    )
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/analyze/project" -Method Post -ContentType "application/json" -Body $projectBody | ConvertTo-Json -Depth 4
```

---

## 5. Running Test Suites

### Backend Pytest Suite
Run all unit, integration, and contract tests with strict warning checking:
```powershell
# From repository root:
.\.venv\Scripts\python.exe -m pytest -W error backend\tests
```
- **Total Tests:** 376 collected (374 passed, 2 opt-in smoke tests skipped by default).
- **Zero Warnings:** `-W error` ensures no unhandled coroutines, deprecations, or runtime warnings exist.

### Frontend Production Build
Verify TypeScript typing and production bundling:
```powershell
# From frontend directory:
npm run build
```

### Playwright Browser End-to-End Suite
Run automated Chromium E2E tests:
```powershell
# From frontend directory:
npm run test:e2e
```
- **Total Scenarios:** 42 browser tests passing across `api_compass.spec.ts`, `project_analysis.spec.ts`, `sse_parser.spec.ts`, and `transparency.spec.ts`.
- Automatically boots an isolated backend process with `data/test_e2e.db` and a preview frontend server.

---

## 6. Stopping Servers

To stop development servers:
- Press `Ctrl + C` in **Terminal 1** (Uvicorn backend).
- Press `Ctrl + C` in **Terminal 2** (Vite frontend).
- The servers terminate gracefully without leaving orphaned background processes or file locks.
