#!/usr/bin/env bash
# Start API Compass local development stack (Backend + Frontend)

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

# Ensure data directory exists
mkdir -p "$REPO_ROOT/data"

# Check if backend is already listening
if curl -s -f -m 2 "http://127.0.0.1:8000/api/v1/health" >/dev/null 2>&1; then
    echo "Backend is already running on http://127.0.0.1:8000"
else
    echo "Starting Backend API server on http://127.0.0.1:8000..."
    nohup "$REPO_ROOT/.venv/bin/python" -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 > "$REPO_ROOT/data/backend.log" 2>&1 &
    BACKEND_PID=$!
    echo "Backend started with PID $BACKEND_PID (logs: data/backend.log)"
fi

# Check if frontend is already listening
if curl -s -f -m 2 "http://127.0.0.1:5173/" >/dev/null 2>&1; then
    echo "Frontend is already running on http://127.0.0.1:5173"
else
    echo "Starting Frontend dev server on http://127.0.0.1:5173..."
    nohup npm --prefix "$REPO_ROOT/frontend" run dev -- --host 127.0.0.1 --port 5173 > "$REPO_ROOT/data/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo "Frontend started with PID $FRONTEND_PID (logs: data/frontend.log)"
fi

# Wait for backend health check
echo -n "Waiting for backend health check..."
for i in {1..20}; do
    if curl -s -f -m 2 "http://127.0.0.1:8000/api/v1/health" >/dev/null 2>&1; then
        echo " Ready!"
        break
    fi
    sleep 1
    echo -n "."
done

echo ""
"$REPO_ROOT/.agents/skills/manage-dev-stack/scripts/status.sh"
