---
name: manage-dev-stack
description: >-
  Start, stop, inspect, or troubleshoot the local APICompass development stack,
  including the FastAPI Uvicorn backend (port 8000) and Vite React frontend (port 5173).
  Use this skill whenever the user asks to start, stop, restart, deploy, check health, or manage local development servers.
---

# Manage Dev Stack Skill

This skill provides verified operational procedures and executable helpers for managing the APICompass local development services.

## Architecture & Ports

- **Backend API**: `http://127.0.0.1:8000` (FastAPI / Uvicorn ASGI)
  - Health check: `http://127.0.0.1:8000/api/v1/health`
  - OpenAPI docs: `http://127.0.0.1:8000/docs`
- **Frontend UI**: `http://127.0.0.1:5173` (Vite + React + Tailwind + Monaco Editor)
  - Proxies `/api` requests to backend on port 8000.
- **Audit Database**: `data/apicompass.db` (SQLite)

---

## Quick Actions

### 1. Check Service Status
Run the status check script:
```bash
./.agents/skills/manage-dev-stack/scripts/status.sh
```
Or check individual endpoints:
```bash
curl -i http://127.0.0.1:8000/api/v1/health
curl -i http://127.0.0.1:5173/
```

### 2. Start the Stack
Run the startup script:
```bash
./.agents/skills/manage-dev-stack/scripts/start.sh
```

Alternatively, to start manually as background daemons:
- **Backend**:
  ```bash
  ./.venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
  ```
- **Frontend**:
  ```bash
  npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
  ```

### 3. Stop the Stack
Run the shutdown script:
```bash
./.agents/skills/manage-dev-stack/scripts/stop.sh
```

---

## Troubleshooting Common Issues

1. **Port In Use (8000 or 5173)**:
   Check running processes:
   ```bash
   ss -tuln | grep -E ':8000|:5173'
   pgrep -fl uvicorn
   ```
   Kill rogue processes with `./.agents/skills/manage-dev-stack/scripts/stop.sh`.

2. **CORS Errors**:
   Verify `.env` has `FRONTEND_ORIGIN=http://localhost:5173` matching the frontend URL.

3. **Mock Mode vs Live Mode**:
   Check `MOCK_MODE` in `.env`:
   - `MOCK_MODE=true`: Deterministic offline mock fixtures (safe without API key).
   - `MOCK_MODE=false`: Live TinyFish retrieval (requires `TINYFISH_API_KEY`).

