# APICompass v3 — Docker & Containerization Guide

This guide provides instructions for building, running, verifying, and troubleshooting APICompass v3 using Docker and Docker Compose.

---

## 1. Quick Start

### 1.1 Prerequisites
- Docker Engine 24+ or Docker Desktop
- Docker Compose plugin (v2+)

Verify availability on your machine:
```bash
docker --version
docker compose version
```

### 1.2 Start Stack (Offline Mock Mode - Default)
To build and launch both services in background mode:
```bash
docker compose up --build -d
```
- **Backend API:** Available at `http://localhost:8000` (docs at `http://localhost:8000/docs`)
- **Frontend UI:** Available at `http://localhost:5173`
- **Database:** Persistent SQLite audit history stored at `./data/apicompass.db`

### 1.3 Stop Stack
To cleanly stop containers while preserving database state:
```bash
docker compose down
```

---

## 2. Configuration & Modes

APICompass uses environment variables passed at runtime. Docker Compose automatically reads values from your local `.env` file (if present) or falls back to secure defaults.

### 2.1 Offline Mock Mode (Default / Hackathon Demo)
If no external credentials are provided, APICompass operates in complete offline mock mode:
- `MOCK_MODE=true`
- `LLM_PROVIDER=disabled`
- No external network access or paid API keys are required.

To force mock mode explicitly:
```bash
MOCK_MODE=true docker compose up -d
```

### 2.2 Live TinyFish Retrieval Mode
To run with live TinyFish documentation search and fetch:
1. Ensure your `.env` contains:
   ```env
   MOCK_MODE=false
   TINYFISH_API_KEY=your_actual_key_here
   ```
2. Run Docker Compose:
   ```bash
   docker compose up -d
   ```
*(Note: `.env` is listed in `.dockerignore` and is never baked into image layers. Credentials are injected strictly into runtime environment variables).*

---

## 3. Database Persistence

APICompass persists scan audits and contract verification logs to SQLite at `data/apicompass.db`.
- In `docker-compose.yml`, the host directory `./data` is mounted to `/app/data`.
- Any scans saved by the backend inside the container are instantly written to `./data/apicompass.db` on the host machine.
- Running `docker compose down` will **never** delete your audit history.
- To reset or erase database history intentionally:
  ```bash
  rm -f data/apicompass.db data/apicompass.db-wal data/apicompass.db-shm
  ```

---

## 4. Verification & Testing

### 4.1 Confirm Container Status & Health
```bash
docker compose ps
```
Expected output:
```
NAME                  STATUS                    PORTS
apicompass-backend    Up (healthy)              0.0.0.0:8000->8000/tcp
apicompass-frontend   Up (healthy)              0.0.0.0:5173->5173/tcp
```

### 4.2 Query Backend Health Check
```bash
curl -s http://localhost:8000/api/v1/health | jq .
```

### 4.3 Execute Python Contract Analysis
```bash
curl -s -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "source": "import stripe\ncharge = stripe.Charge.create(amount=2000, source=\"tok_123\")",
    "filename": "payment.py",
    "ecosystem": "stripe"
  }' | jq .
```

### 4.4 View Logs
```bash
# Follow logs for all services
docker compose logs -f

# Follow backend logs only
docker compose logs -f backend

# Follow frontend logs only
docker compose logs -f frontend
```

---

## 5. Security & Isolation Controls

1. **Non-Root Execution**: Both the backend (`appuser`, UID 1000) and frontend (`node`, UID 1000) run as non-root users.
2. **Secret Hygiene**: Real `.env` files are excluded in `.dockerignore` and will not appear in `docker history`.
3. **SSRF Protection**: Backend domain allowlisting (`docs.stripe.com`, `stripe.com`, `github.com`) and private IP blocking remain strictly enforced.
4. **CORS Enforcement**: Default allowed origin is `http://localhost:5173`. Wildcards (`*`) remain prohibited.

---

## 6. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| Port 8000 or 5173 in use | Existing host process running | Stop host uvicorn/vite process or check `netstat -tlpn` / `lsof -i :8000`. |
| Frontend cannot reach backend | Host network misconfiguration | Ensure `VITE_API_BASE_URL=http://localhost:8000` is accessible from the host browser. |
| Backend unhealthy | Startup error or DB lock | Inspect logs using `docker compose logs backend`. |
| Permission denied on `./data` | File ownership conflict | Ensure host `./data` is writable: `chmod 777 data`. |

