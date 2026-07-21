"""Application composition root for Insight Sculpture.

This module is responsible ONLY for application initialization.
It performs NO analytics, NO Pandas execution, NO LLM calls, NO business logic.
Its responsibilities are:
- Application startup
- Configuration
- Dependency wiring
- Middleware
- Routers
- Exception handlers
- Lifecycle events
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import analyze_router, stream_router, upload_router
from app.config import Environment, get_settings
from app.core.exceptions import InsightSculptureError
from app.llm.client import LLMError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Application startup time
_app_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle events.

    Initializes services on startup and disposes resources on shutdown.

    Yields:
        None
    """
    settings = get_settings()
    logger.info(f"Starting Insight Sculpture API in {settings.environment.value} mode")

    # Initialize application state
    app.state.startup_time = datetime.now(timezone.utc)
    app.state.request_count = 0

    logger.info("Application initialized successfully")

    try:
        yield
    finally:
        # Cleanup on shutdown
        logger.info("Shutting down Insight Sculpture API")
        # Add any cleanup logic here (e.g., closing connections, clearing caches)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    This is the application factory pattern. It creates the FastAPI instance,
    configures middleware, registers routers, sets up exception handlers,
    and initializes the application state.

    Returns:
        Configured FastAPI application instance.
    """
    settings = get_settings()

    # Create FastAPI application
    app = FastAPI(
        title="Insight Sculpture API",
        description="Conversational AI Data Analytics Platform",
        version="1.0.0",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        contact={
            "name": "Insight Sculpture Team",
            "email": "support@insight-sculpture.com",
        },
        license_info={
            "name": "MIT",
            "identifier": "MIT",
        },
        lifespan=lifespan,
    )

    # Configure middleware
    _configure_middleware(app, settings)

    # Register routers
    _register_routers(app)

    # Register exception handlers
    _register_exception_handlers(app)

    # Register health endpoints
    _register_health_endpoints(app)

    # Configure logging based on environment
    _configure_logging(settings)

    return app


def _configure_middleware(app: FastAPI, settings: Any) -> None:
    """Configure application middleware.

    Args:
        app: FastAPI application instance.
        settings: Application settings.
    """
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_cors_origins(settings),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # GZip middleware for compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Trusted host middleware in production
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"],  # Configure based on deployment
        )

    # Custom middleware for request ID
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        """Add unique request ID to each request."""
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Custom middleware for response time
    @app.middleware("http")
    async def add_response_time(request: Request, call_next):
        """Add response time header to each response."""
        start_time = time.time()
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        return response

    # Custom middleware for request counting
    @app.middleware("http")
    async def count_requests(request: Request, call_next):
        """Count incoming requests for monitoring."""
        app.state.request_count = getattr(app.state, "request_count", 0) + 1
        response = await call_next(request)
        return response

    # Security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers to responses."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


def _get_cors_origins(settings: Any) -> list[str]:
    """Get allowed CORS origins from settings.

    Args:
        settings: Application settings.

    Returns:
        List of allowed CORS origins.
    """
    # In development, allow all origins
    if settings.is_development:
        return ["*"]

    # In production, load from environment or use defaults
    # This should be configured based on deployment
    return [
        "http://localhost:3000",
        "http://localhost:8080",
    ]


def _register_routers(app: FastAPI) -> None:
    """Register API routers.

    Args:
        app: FastAPI application instance.
    """
    app.include_router(upload_router, prefix="/api", tags=["upload"])
    app.include_router(analyze_router, prefix="/api", tags=["analyze"])
    app.include_router(stream_router, prefix="/api", tags=["stream"])


def _register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers.

    Args:
        app: FastAPI application instance.
    """
    # Pydantic validation errors
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle Pydantic validation errors."""
        logger.warning(f"Validation error: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                },
            },
        )

    # HTTP exceptions
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Handle HTTP exceptions."""
        logger.warning(f"HTTP exception: {exc.status_code} - {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": "HTTP_ERROR",
                    "message": exc.detail,
                    "details": None,
                },
            },
        )

    # LLM errors
    @app.exception_handler(LLMError)
    async def llm_exception_handler(request: Request, exc: LLMError):
        """Handle LLM-related errors."""
        logger.error(f"LLM error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "LLM_ERROR",
                    "message": "An error occurred while communicating with the LLM provider",
                    "details": None,
                },
            },
        )

    # Analytics / Insight Sculpture errors
    @app.exception_handler(InsightSculptureError)
    async def insight_sculpture_exception_handler(request: Request, exc: InsightSculptureError):
        """Handle Insight Sculpture domain errors with structured responses."""
        logger.warning(f"Analytics error: {exc}")
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "success": False,
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
        )

    # Runtime errors
    @app.exception_handler(RuntimeError)
    async def runtime_exception_handler(request: Request, exc: RuntimeError):
        """Handle runtime errors."""
        logger.error(f"Runtime error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "RUNTIME_ERROR",
                    "message": "An unexpected runtime error occurred",
                    "details": None,
                },
            },
        )

    # Generic exception handler
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal server error occurred",
                    "details": None,
                },
            },
        )


def _register_health_endpoints(app: FastAPI) -> None:
    """Register health check endpoints.

    Args:
        app: FastAPI application instance.
    """
    @app.get("/", tags=["root"])
    async def root():
        """Root endpoint with API metadata."""
        settings = get_settings()
        return {
            "name": "Insight Sculpture API",
            "version": "1.0.0",
            "description": "Conversational AI Data Analytics Platform",
            "environment": settings.environment.value,
            "documentation": "/docs" if settings.is_development else None,
        }

    @app.get("/health", tags=["health"])
    async def health():
        """Health check endpoint."""
        settings = get_settings()
        uptime = time.time() - _app_start_time
        return {
            "status": "healthy",
            "uptime_seconds": uptime,
            "version": "1.0.0",
            "environment": settings.environment.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/ready", tags=["health"])
    async def readiness():
        """Readiness probe endpoint."""
        # Check if all dependencies are ready
        # This can be extended to check database connections, external services, etc.
        return {
            "status": "ready",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/live", tags=["health"])
    async def liveness():
        """Liveness probe endpoint."""
        # Check if the application is alive
        return {
            "status": "alive",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def _configure_logging(settings: Any) -> None:
    """Configure logging based on environment.

    Args:
        settings: Application settings.
    """
    if settings.is_production:
        # Production logging configuration
        logging.getLogger().setLevel(logging.WARNING)
        # In production, you might want to add file logging, structured logging, etc.
    else:
        # Development logging configuration
        logging.getLogger().setLevel(logging.DEBUG)


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        log_level="info" if settings.is_development else "warning",
    )
