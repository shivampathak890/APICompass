"""Test suite for health endpoint, configuration, and CORS policies."""

from datetime import datetime
import pytest
from httpx import AsyncClient

from app.config import settings


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client: AsyncClient) -> None:
    """Verify GET /api/v1/health returns HTTP 200 OK."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_schema(client: AsyncClient) -> None:
    """Verify response contains all required fields with expected types."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()

    assert "status" in data
    assert data["status"] == "healthy"
    assert "service" in data
    assert data["service"] == "apicompass-api"
    assert "version" in data
    assert "timestamp" in data
    assert "mock_mode" in data
    assert isinstance(data["mock_mode"], bool)


@pytest.mark.asyncio
async def test_health_timestamp_valid_iso8601(client: AsyncClient) -> None:
    """Verify timestamp is a valid ISO-8601 UTC timestamp."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    
    timestamp_str = data["timestamp"]
    # fromisoformat should parse without raising ValueError
    parsed_dt = datetime.fromisoformat(timestamp_str)
    assert parsed_dt.tzinfo is not None, "Timestamp must include timezone info (UTC)"


@pytest.mark.asyncio
async def test_health_version_matches_config(client: AsyncClient) -> None:
    """Verify the reported version matches the configured application version."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == settings.APP_VERSION


@pytest.mark.asyncio
async def test_missing_optional_credentials_allows_startup(client: AsyncClient) -> None:
    """Verify health check succeeds even when optional credentials are unset."""
    # settings.TINYFISH_API_KEY and settings.LLM_API_KEY can be None
    assert settings.TINYFISH_API_KEY is None or isinstance(settings.TINYFISH_API_KEY, str)
    assert settings.LLM_API_KEY is None or isinstance(settings.LLM_API_KEY, str)
    
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_cors_allows_configured_frontend_origin(client: AsyncClient) -> None:
    """Verify CORS headers are returned for the configured frontend origin."""
    headers = {
        "Origin": settings.FRONTEND_ORIGIN,
        "Access-Control-Request-Method": "GET",
    }
    response = await client.options("/api/v1/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == settings.FRONTEND_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_cors_rejects_unapproved_origin(client: AsyncClient) -> None:
    """Verify CORS headers do not grant access to unapproved arbitrary origins."""
    headers = {
        "Origin": "http://unapproved-malicious-origin.com",
        "Access-Control-Request-Method": "GET",
    }
    response = await client.options("/api/v1/health", headers=headers)
    # FastAPI CORSMiddleware does not echo unapproved origins in access-control-allow-origin
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "http://unapproved-malicious-origin.com"
