#!/usr/bin/env bash
# Stop API Compass local development servers

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

echo "Stopping API Compass local servers..."

# Stop backend process if running
BACKEND_PIDS=$(pgrep -f "uvicorn app.main:create_app" || true)
if [ -n "$BACKEND_PIDS" ]; then
    echo "Terminating Backend (PID(s): $BACKEND_PIDS)..."
    kill $BACKEND_PIDS 2>/dev/null || true
    sleep 1
fi

# Stop frontend process if running
FRONTEND_PIDS=$(pgrep -f "vite.*5173" || true)
if [ -n "$FRONTEND_PIDS" ]; then
    echo "Terminating Frontend (PID(s): $FRONTEND_PIDS)..."
    kill $FRONTEND_PIDS 2>/dev/null || true
    sleep 1
fi

# Fallback: check ports 8000 and 5173 using fuser or lsof if available
if command -v fuser >/dev/null 2>&1; then
    fuser -k 8000/tcp 2>/dev/null || true
    fuser -k 5173/tcp 2>/dev/null || true
fi

echo "API Compass servers stopped."
