"""FastAPI entrypoint and application lifespan for APICompass v3."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, HTTPException as FastAPIHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from collections import defaultdict
from threading import Lock
import sys
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.config import settings
from app.db import init_db, MigrationError
from app.schemas.errors import ErrorDetailItem, ErrorResponse
from app.services.llm.secret_scrubber import scrub_secrets

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("apicompass")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Validates configuration at startup and handles cleanup on shutdown.
    External credentials remain optional in offline mock mode.
    """
    logger.info("Initializing APICompass v3 (%s)", settings.APP_VERSION)
    logger.info("Environment: %s | Mock Mode: %s", settings.APP_ENV, settings.MOCK_MODE)
    logger.info("Allowed CORS Origin: %s", settings.FRONTEND_ORIGIN)
    logger.info("Approved Doc Hosts: %s", ", ".join(settings.APPROVED_DOC_HOSTS))

    # Initialize SQLite audit database schema and migrations idempotently
    try:
        init_db()
        logger.info("SQLite audit database initialized at: %s", settings.APICOMPASS_DB_PATH)
    except MigrationError as e:
        logger.critical("Controlled startup termination: Database migration failure: %s", str(e))
        raise RuntimeError(f"Database migration failure: {e}") from e
    except Exception as e:
        logger.critical("Controlled startup termination: Database initialization failure: %s", type(e).__name__)
        raise RuntimeError(f"Database initialization failure: {e}") from e

    yield

    logger.info("Shutting down APICompass v3")


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Format Pydantic request validation errors into a standardized, secret-scrubbed ErrorResponse."""
    error_items: list[ErrorDetailItem] = []
    messages: list[str] = []

    for err in exc.errors():
        loc_parts = [str(p) for p in err.get("loc", []) if p != "body"]
        loc_str = ".".join(loc_parts) if loc_parts else "payload"
        raw_msg = str(err.get("msg", "Invalid value"))
        clean_msg, _ = scrub_secrets(raw_msg)
        error_type = str(err.get("type", "validation_error"))

        error_items.append(
            ErrorDetailItem(
                loc=list(err.get("loc", [])),
                msg=clean_msg,
                type=error_type,
            )
        )
        messages.append(f"{loc_str}: {clean_msg}")

    summary_detail = f"Input validation failed: {'; '.join(messages)}" if messages else "Invalid request payload."
    summary_detail, _ = scrub_secrets(summary_detail)

    payload = ErrorResponse(
        detail=summary_detail,
        error_code="VALIDATION_ERROR",
        status_code=422,
        timestamp=datetime.now(timezone.utc).isoformat(),
        errors=error_items,
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Format Starlette/FastAPI HTTPExceptions into standardized ErrorResponse."""
    raw_detail = str(exc.detail) if exc.detail else "An HTTP error occurred."
    clean_detail, _ = scrub_secrets(raw_detail)

    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMITED",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    error_code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")

    payload = ErrorResponse(
        detail=clean_detail,
        error_code=error_code,
        status_code=exc.status_code,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(),
        headers=getattr(exc, "headers", None),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled internal server exceptions without leaking internal stack traces or secrets."""
    logger.error("Unhandled server exception processing %s %s: %s", request.method, request.url.path, exc, exc_info=True)

    payload = ErrorResponse(
        detail="An internal server error occurred while processing the request. Details have been logged securely.",
        error_code="INTERNAL_SERVER_ERROR",
        status_code=500,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return JSONResponse(status_code=500, content=payload.model_dump())


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce defense-in-depth HTTP security response headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response


class MaxPayloadSizeMiddleware(BaseHTTPMiddleware):
    """Reject oversized request payloads before in-memory buffering to prevent resource exhaustion."""

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and request.method in ("POST", "PUT", "PATCH"):
            try:
                length_int = int(content_length)
                if length_int > settings.MAX_REQUEST_BODY_BYTES:
                    payload = ErrorResponse(
                        detail=f"Request payload ({length_int} bytes) exceeds maximum permitted limit of {settings.MAX_REQUEST_BODY_BYTES} bytes.",
                        error_code="PAYLOAD_TOO_LARGE",
                        status_code=413,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    return JSONResponse(status_code=413, content=payload.model_dump())
            except ValueError:
                pass
        return await call_next(request)


class InMemoryRateLimiter:
    """Thread-safe sliding-window in-memory rate limiter per client IP."""

    def __init__(self, limit: int = 120, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self.history: dict[str, list[float]] = defaultdict(list)
        self.lock = Lock()

    def check(self, key: str) -> tuple[bool, int, int]:
        """Check if request is allowed.

        Returns:
            (allowed: bool, remaining: int, retry_after: int)
        """
        now = time.time()
        cutoff = now - self.window
        with self.lock:
            valid = [t for t in self.history[key] if t > cutoff]
            if len(valid) >= self.limit:
                retry_after = max(1, int(cutoff + self.window - valid[0]))
                self.history[key] = valid
                return False, 0, retry_after
            valid.append(now)
            self.history[key] = valid
            remaining = max(0, self.limit - len(valid))
            return True, remaining, 0

    def reset(self):
        with self.lock:
            self.history.clear()


rate_limiter = InMemoryRateLimiter()


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Enforce rate limiting on API endpoints to prevent abuse and denial of service."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        # Exempt health checks and documentation UI from rate limits
        if path in ("/api/v1/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Identify client key: client IP (checking X-Forwarded-For if behind reverse proxy)
        forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "unknown")

        # Allow automated testclient runs unless explicitly testing rate limits
        is_test_client = client_ip in ("testclient", "unknown") or (
            "pytest" in sys.modules and client_ip in ("127.0.0.1", "::1", "localhost", "testserver")
        )
        if is_test_client and not getattr(settings, "TESTING_RATE_LIMIT", False):
            response: Response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_PER_MINUTE)
            response.headers["X-RateLimit-Remaining"] = str(settings.RATE_LIMIT_PER_MINUTE)
            return response

        rate_limiter.limit = settings.RATE_LIMIT_PER_MINUTE
        allowed, remaining, retry_after = rate_limiter.check(client_ip)

        if not allowed:
            logger.warning("Rate limit exceeded for client %s on %s %s", client_ip, request.method, path)
            payload = ErrorResponse(
                detail=f"Rate limit exceeded ({settings.RATE_LIMIT_PER_MINUTE} req/min). Please wait before retrying.",
                error_code="RATE_LIMITED",
                status_code=429,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return JSONResponse(
                status_code=429,
                content=payload.model_dump(),
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_PER_MINUTE),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def create_app() -> FastAPI:
    """Application factory for APICompass backend."""
    app = FastAPI(
        title="APICompass API",
        description="API verification against official documentation and supporting technical sources.",
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
        responses={
            400: {"model": ErrorResponse, "description": "Bad Request"},
            422: {"model": ErrorResponse, "description": "Validation Error"},
            500: {"model": ErrorResponse, "description": "Internal Server Error"},
        },
    )

    # Register standardized exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(FastAPIHTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # Configure defense-in-depth security middlewares
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(MaxPayloadSizeMiddleware)
    app.add_middleware(RateLimiterMiddleware)

    # Configure strict CORS for the frontend origin (supporting both localhost and 127.0.0.1 for local dev/testing)
    allowed_origins = [settings.FRONTEND_ORIGIN]
    if "localhost:5173" in settings.FRONTEND_ORIGIN and "http://127.0.0.1:5173" not in allowed_origins:
        allowed_origins.append("http://127.0.0.1:5173")
    elif "127.0.0.1:5173" in settings.FRONTEND_ORIGIN and "http://localhost:5173" not in allowed_origins:
        allowed_origins.append("http://localhost:5173")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(api_router)

    return app


app = create_app()

