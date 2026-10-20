#!/usr/bin/env bash
# Check API Compass local stack status

set -e

BACKEND_PORT=8000
FRONTEND_PORT=5173
HEALTH_URL="http://127.0.0.1:${BACKEND_PORT}/api/v1/health"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}/"

echo "=== API Compass Local Services Status ==="

# Check backend
echo -n "Backend (port ${BACKEND_PORT}): "
if curl -s -f -m 3 "${HEALTH_URL}" >/dev/null 2>&1; then
    HEALTH_JSON=$(curl -s -m 3 "${HEALTH_URL}")
    STATUS=$(echo "${HEALTH_JSON}" | grep -o '"status":"[^"]*"' | cut -d':' -f2 | tr -d '"')
    MOCK=$(echo "${HEALTH_JSON}" | grep -o '"mock_mode":[^,}]*' | cut -d':' -f2)
    echo "ONLINE (Status: ${STATUS}, Mock Mode: ${MOCK})"
else
    echo "OFFLINE"
fi

# Check frontend
echo -n "Frontend (port ${FRONTEND_PORT}): "
if curl -s -f -m 3 "${FRONTEND_URL}" >/dev/null 2>&1; then
    echo "ONLINE (Vite dev server reachable)"
else
    echo "OFFLINE"
fi

echo "========================================="

