"""API module for FastAPI endpoints."""

from __future__ import annotations

from app.api.analyze import router as analyze_router
from app.api.stream import router as stream_router
from app.api.upload import router as upload_router

__all__ = ["analyze_router", "stream_router", "upload_router"]
