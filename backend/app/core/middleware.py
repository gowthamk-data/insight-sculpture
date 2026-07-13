"""Centralized middleware system for Insight Sculpture.

This module provides reusable FastAPI middleware components.
Middleware is responsible for HTTP request/response processing only.
It performs NO business logic, NO LLM calls, NO analytics execution, NO dataset manipulation.

Security: Middleware never exposes API keys, stack traces, or internal details.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from fastapi import HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import get_settings
from app.core.exceptions import (
    InsightSculptureError,
    InternalServerError,
    ValidationError as AppValidationError,
)

logger = logging.getLogger(__name__)


# ============================================================
# Request ID Middleware
# ============================================================


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add unique request IDs to all requests.

    Generates a unique request ID for each request, reuses incoming
    X-Request-ID header if present, attaches to request.state, and adds
    X-Request-ID to response headers for traceability.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add request ID.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            HTTP response with X-Request-ID header.
        """
        # Reuse incoming request ID if present, otherwise generate new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


# ============================================================
# Request Timing Middleware
# ============================================================


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Middleware to measure and report request processing time.

    Measures total request processing time in milliseconds, stores it in
    request.state.processing_time_ms, and adds X-Process-Time header to response.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and measure timing.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            HTTP response with X-Process-Time header.
        """
        start_time = time.time()

        response = await call_next(request)

        processing_time_ms = (time.time() - start_time) * 1000
        request.state.processing_time_ms = processing_time_ms
        response.headers["X-Process-Time"] = f"{processing_time_ms:.2f}ms"

        return response


# ============================================================
# Logging Middleware
# ============================================================


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests and responses.

    Logs request method, path, response status, processing time, and request ID.
    Never logs sensitive data like API keys, prompts, uploaded datasets, or personal data.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log details.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            HTTP response.
        """
        request_id = getattr(request.state, "request_id", "unknown")
        method = request.method
        path = request.url.path

        # Log request
        logger.info(
            f"Request started",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "client": request.client.host if request.client else "unknown",
            },
        )

        start_time = time.time()
        response = await call_next(request)
        processing_time_ms = (time.time() - start_time) * 1000

        # Log response
        logger.info(
            f"Request completed",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "processing_time_ms": f"{processing_time_ms:.2f}",
            },
        )

        return response


# ============================================================
# Security Headers Middleware
# ============================================================


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses.

    Adds security headers to protect against common web vulnerabilities:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: restricts browser features
    - Strict-Transport-Security: HTTPS enforcement (production only)
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add security headers.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            HTTP response with security headers.
        """
        response = await call_next(request)

        # Content type protection
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Clickjacking protection
        response.headers["X-Frame-Options"] = "DENY"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy (restrict browser features)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # HSTS (HTTPS enforcement) in production only
        settings = get_settings()
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


# ============================================================
# Error Handling Middleware
# ============================================================


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware to catch and handle unhandled exceptions.

    Converts custom InsightSculptureError exceptions into standardized JSON responses.
    Handles ValidationError, HTTPException, RuntimeError, and unhandled exceptions.
    Never exposes stack traces or internal implementation details.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and handle exceptions.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler in the chain.

        Returns:
            HTTP response with standardized error format.
        """
        request_id = getattr(request.state, "request_id", "unknown")

        try:
            return await call_next(request)
        except InsightSculptureError as exc:
            # Handle custom application exceptions
            logger.warning(
                f"Application error: {exc.error_code}",
                extra={
                    "request_id": request_id,
                    "error_code": exc.error_code,
                    "http_status": exc.http_status,
                },
            )
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "success": False,
                    "error": {
                        "code": exc.error_code,
                        "message": exc.message,
                        "request_id": request_id,
                        "details": exc.details,
                    },
                },
            )
        except RequestValidationError as exc:
            # Handle Pydantic validation errors
            logger.warning(
                f"Validation error: {len(exc.errors())} errors",
                extra={
                    "request_id": request_id,
                    "error_count": len(exc.errors()),
                },
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Request validation failed",
                        "request_id": request_id,
                        "details": exc.errors(),
                    },
                },
            )
        except HTTPException as exc:
            # Handle FastAPI HTTP exceptions
            logger.warning(
                f"HTTP exception: {exc.status_code}",
                extra={
                    "request_id": request_id,
                    "status_code": exc.status_code,
                },
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "success": False,
                    "error": {
                        "code": "HTTP_ERROR",
                        "message": str(exc.detail),
                        "request_id": request_id,
                        "details": None,
                    },
                },
            )
        except RuntimeError as exc:
            # Handle runtime errors
            logger.error(
                f"Runtime error: {str(exc)}",
                extra={
                    "request_id": request_id,
                },
                exc_info=True,
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "error": {
                        "code": "RUNTIME_ERROR",
                        "message": "An unexpected runtime error occurred",
                        "request_id": request_id,
                        "details": None,
                    },
                },
            )
        except Exception as exc:
            # Handle all unhandled exceptions
            logger.error(
                f"Unhandled exception: {str(exc)}",
                extra={
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "success": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An internal server error occurred",
                        "request_id": request_id,
                        "details": None,
                    },
                },
            )


# ============================================================
# Middleware Helper Functions
# ============================================================


def get_cors_origins() -> list[str]:
    """Get allowed CORS origins from configuration.

    Returns:
        List of allowed CORS origins. Returns ["*"] in development.
    """
    settings = get_settings()

    if settings.is_development:
        return ["*"]

    # In production, load from environment or use defaults
    # This should be configured based on deployment
    return [
        "http://localhost:3000",
        "http://localhost:8080",
    ]


def get_trusted_hosts() -> list[str]:
    """Get trusted hosts from configuration.

    Returns:
        List of trusted hostnames. Returns ["*"] in development.
    """
    settings = get_settings()

    if settings.is_development:
        return ["*"]

    # In production, configure based on deployment
    # This should be set to actual allowed hostnames
    return ["*"]


# ============================================================
# Middleware Registration
# ============================================================


def register_middlewares(app: ASGIApp) -> ASGIApp:
    """Register all middleware in the correct order.

    Middleware order is critical:
    1. Request ID (first, to ensure all requests have IDs)
    2. Timing (measure total processing time)
    3. Logging (log all requests with timing)
    4. Security Headers (add security headers to responses)
    5. Error Handling (catch and handle exceptions)

    Args:
        app: FastAPI application instance.

    Returns:
        Application with middleware registered.
    """
    settings = get_settings()

    # 1. Request ID Middleware
    app.add_middleware(RequestIDMiddleware)

    # 2. Request Timing Middleware
    app.add_middleware(RequestTimingMiddleware)

    # 3. Logging Middleware
    app.add_middleware(LoggingMiddleware)

    # 4. Security Headers Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 5. Error Handling Middleware
    app.add_middleware(ErrorHandlingMiddleware)

    # 6. CORS Middleware (standard FastAPI middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # 7. GZip Middleware (standard FastAPI middleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 8. Trusted Host Middleware (production only)
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=get_trusted_hosts(),
        )

    return app
