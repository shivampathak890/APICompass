# ==============================================================================
# APICompass v3 - Backend Dockerfile
# Production-ready, non-root Python container for FastAPI & Evidence Engine
# ==============================================================================

FROM python:3.12-slim

# Enforce secure Python runtime defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    API_HOST=0.0.0.0 \
    API_PORT=8000

WORKDIR /app

# Create dedicated non-root application user/group (uid:gid 1000:1000)
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

# Install pinned dependencies first to maximize Docker layer cache
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend application package
COPY backend/app ./backend/app

# Ensure SQLite audit data directory exists with non-root ownership
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Zero-dependency health check querying the native APICompass health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

# Launch ASGI server bound to all interfaces
CMD ["uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

