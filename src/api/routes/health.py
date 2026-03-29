"""Health check endpoint — used by Docker health checks and uptime monitors."""

from fastapi import APIRouter
from src.config import settings

router = APIRouter(tags=["health"])

_VERSION = "0.1.0"


@router.get("/api/v1/health")
async def health() -> dict:
    """Return service health status. No auth required."""
    return {"status": "ok", "version": _VERSION}
