"""Top-level API router registering versioned sub-routers."""

from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.analyze import router as analyze_router
from app.api.v1.docs import router as docs_router
from app.api.v1.fixes import router as fixes_router
from app.api.v1.scans import router as scans_router

api_router = APIRouter(prefix="/api")

# Register v1 routes
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(analyze_router)
v1_router.include_router(docs_router)
v1_router.include_router(fixes_router)
v1_router.include_router(scans_router)


api_router.include_router(v1_router)
