"""Centralized exception system for Insight Sculpture.

This module defines the complete exception hierarchy for the application.
All custom exceptions should inherit from the base InsightSculptureError.
This ensures consistent error handling, logging, and API responses across the application.

Security: Exception messages never expose API keys, passwords, stack traces,
or internal implementation details to clients.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# HTTP Status Codes
HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_403_FORBIDDEN = 403
HTTP_404_NOT_FOUND = 404
HTTP_409_CONFLICT = 409
HTTP_422_UNPROCESSABLE_ENTITY = 422
HTTP_500_INTERNAL_SERVER_ERROR = 500
HTTP_503_SERVICE_UNAVAILABLE = 503


@dataclass
class InsightSculptureError(Exception):
    """Base exception for all Insight Sculpture errors.

    All custom exceptions should inherit from this base class to ensure
    consistent error handling, logging, and API responses.

    Attributes:
        message: Human-readable error message for clients.
        error_code: Machine-readable error code for programmatic handling.
        details: Additional context or metadata about the error.
        http_status: HTTP status code for API responses.
        timestamp: When the error occurred (UTC).
    """

    message: str
    error_code: str
    details: dict[str, Any] | None = None
    http_status: int = HTTP_500_INTERNAL_SERVER_ERROR
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        """Return string representation of the error."""
        return f"[{self.error_code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses.

        Returns:
            Dictionary representation of the error.
        """
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_json(self) -> str:
        """Convert exception to JSON string.

        Returns:
            JSON string representation of the error.
        """
        return json.dumps(self.to_dict())

    def to_log_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging.

        Includes additional context for debugging while keeping client-facing
        information separate.

        Returns:
            Dictionary representation suitable for logging.
        """
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "http_status": self.http_status,
            "timestamp": self.timestamp.isoformat(),
            "exception_type": self.__class__.__name__,
        }


# ============================================================
# Dataset Exceptions
# ============================================================


class DatasetError(InsightSculptureError):
    """Base exception for dataset-related errors."""

    def __init__(
        self,
        message: str = "Dataset operation failed",
        error_code: str = "DATASET_ERROR",
        details: dict[str, Any] | None = None,
        http_status: int = HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(message, error_code, details, http_status)


class FileUploadError(DatasetError):
    """Raised when file upload fails."""

    def __init__(
        self,
        message: str = "File upload failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="FILE_UPLOAD_ERROR",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class UnsupportedFileTypeError(DatasetError):
    """Raised when uploaded file type is not supported."""

    def __init__(
        self,
        file_type: str,
        supported_types: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Unsupported file type: {file_type}"
        if supported_types:
            message += f". Supported types: {', '.join(supported_types)}"
        error_details = details or {}
        error_details["file_type"] = file_type
        if supported_types:
            error_details["supported_types"] = supported_types
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_FILE_TYPE",
            details=error_details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class DatasetParsingError(DatasetError):
    """Raised when dataset file cannot be parsed."""

    def __init__(
        self,
        message: str = "Failed to parse dataset file",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DATASET_PARSING_ERROR",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class DatasetEmptyError(DatasetError):
    """Raised when dataset is empty."""

    def __init__(
        self,
        message: str = "Dataset is empty",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DATASET_EMPTY_ERROR",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class DatasetTooLargeError(DatasetError):
    """Raised when dataset exceeds size limits."""

    def __init__(
        self,
        size_bytes: int | None = None,
        max_size_bytes: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "Dataset exceeds maximum size limit"
        error_details = details or {}
        if size_bytes is not None:
            error_details["size_bytes"] = size_bytes
        if max_size_bytes is not None:
            error_details["max_size_bytes"] = max_size_bytes
        super().__init__(
            message=message,
            error_code="DATASET_TOO_LARGE",
            details=error_details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class DatasetProfileError(DatasetError):
    """Raised when dataset profiling fails."""

    def __init__(
        self,
        message: str = "Failed to profile dataset",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DATASET_PROFILE_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class SessionError(DatasetError):
    """Base exception for session-related errors."""

    def __init__(
        self,
        message: str = "Session operation failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="SESSION_ERROR",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class SessionNotFoundError(SessionError):
    """Raised when requested session does not exist."""

    def __init__(
        self,
        session_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Session not found: {session_id}"
        error_details = details or {}
        error_details["session_id"] = session_id
        super().__init__(
            message=message,
            error_code="SESSION_NOT_FOUND",
            details=error_details,
            http_status=HTTP_404_NOT_FOUND,
        )


class ExpiredSessionError(SessionError):
    """Raised when session has expired."""

    def __init__(
        self,
        session_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Session has expired: {session_id}"
        error_details = details or {}
        error_details["session_id"] = session_id
        super().__init__(
            message=message,
            error_code="EXPIRED_SESSION",
            details=error_details,
            http_status=HTTP_400_BAD_REQUEST,
        )


# ============================================================
# Analytics Exceptions
# ============================================================


class AnalyticsError(InsightSculptureError):
    """Base exception for analytics-related errors."""

    def __init__(
        self,
        message: str = "Analytics operation failed",
        error_code: str = "ANALYTICS_ERROR",
        details: dict[str, Any] | None = None,
        http_status: int = HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(message, error_code, details, http_status)


class InvalidAnalysisPlanError(AnalyticsError):
    """Raised when analysis plan is invalid."""

    def __init__(
        self,
        message: str = "Invalid analysis plan",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_ANALYSIS_PLAN",
            details=details,
            http_status=HTTP_422_UNPROCESSABLE_ENTITY,
        )


class UnsupportedOperationError(AnalyticsError):
    """Raised when requested operation is not supported."""

    def __init__(
        self,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Unsupported operation: {operation}"
        error_details = details or {}
        error_details["operation"] = operation
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_OPERATION",
            details=error_details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class ColumnNotFoundError(AnalyticsError):
    """Raised when specified column does not exist in dataset."""

    def __init__(
        self,
        column: str | list[str],
        available_columns: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(column, list):
            message = f"Columns not found: {', '.join(column)}"
        else:
            message = f"Column not found: {column}"
        error_details = details or {}
        error_details["column"] = column
        if available_columns:
            error_details["available_columns"] = available_columns
        super().__init__(
            message=message,
            error_code="COLUMN_NOT_FOUND",
            details=error_details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class InvalidAggregationError(AnalyticsError):
    """Raised when aggregation function is invalid."""

    def __init__(
        self,
        aggregation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Invalid aggregation function: {aggregation}"
        error_details = details or {}
        error_details["aggregation"] = aggregation
        super().__init__(
            message=message,
            error_code="INVALID_AGGREGATION",
            details=error_details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class InvalidFilterError(AnalyticsError):
    """Raised when filter condition is invalid."""

    def __init__(
        self,
        message: str = "Invalid filter condition",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_FILTER",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class InvalidChartConfigurationError(AnalyticsError):
    """Raised when chart configuration is invalid."""

    def __init__(
        self,
        message: str = "Invalid chart configuration",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_CHART_CONFIGURATION",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class ExecutionError(AnalyticsError):
    """Raised when analytics execution fails."""

    def __init__(
        self,
        message: str = "Analytics execution failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="EXECUTION_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ChartGenerationError(AnalyticsError):
    """Raised when chart generation fails."""

    def __init__(
        self,
        message: str = "Chart generation failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="CHART_GENERATION_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ============================================================
# LLM Exceptions
# ============================================================


class LLMError(InsightSculptureError):
    """Base exception for LLM-related errors."""

    def __init__(
        self,
        message: str = "LLM operation failed",
        error_code: str = "LLM_ERROR",
        details: dict[str, Any] | None = None,
        http_status: int = HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        super().__init__(message, error_code, details, http_status)


class ProviderConfigurationError(LLMError):
    """Raised when LLM provider is misconfigured."""

    def __init__(
        self,
        message: str = "LLM provider configuration error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="PROVIDER_CONFIGURATION_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class AuthenticationError(LLMError):
    """Raised when LLM provider authentication fails."""

    def __init__(
        self,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "LLM provider authentication failed"
        error_details = details or {}
        if provider:
            error_details["provider"] = provider
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            details=error_details,
            http_status=HTTP_401_UNAUTHORIZED,
        )


class RateLimitError(LLMError):
    """Raised when LLM provider rate limit is exceeded."""

    def __init__(
        self,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "LLM provider rate limit exceeded"
        error_details = details or {}
        if provider:
            error_details["provider"] = provider
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_ERROR",
            details=error_details,
            http_status=HTTP_429_TOO_MANY_REQUESTS if "HTTP_429_TOO_MANY_REQUESTS" in globals() else 429,
        )


class TimeoutError(LLMError):
    """Raised when LLM provider request times out."""

    def __init__(
        self,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "LLM provider request timed out"
        error_details = details or {}
        if provider:
            error_details["provider"] = provider
        super().__init__(
            message=message,
            error_code="TIMEOUT_ERROR",
            details=error_details,
            http_status=HTTP_503_SERVICE_UNAVAILABLE,
        )


class ProviderConnectionError(LLMError):
    """Raised when connection to LLM provider fails."""

    def __init__(
        self,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "Failed to connect to LLM provider"
        error_details = details or {}
        if provider:
            error_details["provider"] = provider
        super().__init__(
            message=message,
            error_code="PROVIDER_CONNECTION_ERROR",
            details=error_details,
            http_status=HTTP_503_SERVICE_UNAVAILABLE,
        )


class InvalidLLMResponseError(LLMError):
    """Raised when LLM provider returns invalid response."""

    def __init__(
        self,
        message: str = "Invalid response from LLM provider",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_LLM_RESPONSE",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class JSONValidationError(LLMError):
    """Raised when LLM response fails JSON validation."""

    def __init__(
        self,
        message: str = "LLM response failed JSON validation",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="JSON_VALIDATION_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class PlannerError(LLMError):
    """Raised when analysis planning fails."""

    def __init__(
        self,
        message: str = "Analysis planning failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="PLANNER_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ExplainerError(LLMError):
    """Raised when explanation generation fails."""

    def __init__(
        self,
        message: str = "Explanation generation failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="EXPLAINER_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ============================================================
# API Exceptions
# ============================================================


class APIError(InsightSculptureError):
    """Base exception for API-related errors."""

    def __init__(
        self,
        message: str = "API request failed",
        error_code: str = "API_ERROR",
        details: dict[str, Any] | None = None,
        http_status: int = HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        super().__init__(message, error_code, details, http_status)


class BadRequestError(APIError):
    """Raised when request is malformed."""

    def __init__(
        self,
        message: str = "Bad request",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="BAD_REQUEST",
            details=details,
            http_status=HTTP_400_BAD_REQUEST,
        )


class UnauthorizedError(APIError):
    """Raised when request lacks valid authentication."""

    def __init__(
        self,
        message: str = "Unauthorized",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="UNAUTHORIZED",
            details=details,
            http_status=HTTP_401_UNAUTHORIZED,
        )


class ForbiddenError(APIError):
    """Raised when request lacks valid authorization."""

    def __init__(
        self,
        message: str = "Forbidden",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="FORBIDDEN",
            details=details,
            http_status=HTTP_403_FORBIDDEN,
        )


class ResourceNotFoundError(APIError):
    """Raised when requested resource does not exist."""

    def __init__(
        self,
        resource: str,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Resource not found: {resource}"
        error_details = details or {}
        error_details["resource"] = resource
        if resource_id:
            error_details["resource_id"] = resource_id
            message += f" ({resource_id})"
        super().__init__(
            message=message,
            error_code="RESOURCE_NOT_FOUND",
            details=error_details,
            http_status=HTTP_404_NOT_FOUND,
        )


class ConflictError(APIError):
    """Raised when request conflicts with current state."""

    def __init__(
        self,
        message: str = "Resource conflict",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="CONFLICT",
            details=details,
            http_status=HTTP_409_CONFLICT,
        )


class ValidationError(APIError):
    """Raised when request validation fails."""

    def __init__(
        self,
        message: str = "Request validation failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details=details,
            http_status=HTTP_422_UNPROCESSABLE_ENTITY,
        )


# ============================================================
# Internal Exceptions
# ============================================================


class InternalError(InsightSculptureError):
    """Base exception for internal application errors."""

    def __init__(
        self,
        message: str = "Internal error occurred",
        error_code: str = "INTERNAL_ERROR",
        details: dict[str, Any] | None = None,
        http_status: int = HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        super().__init__(message, error_code, details, http_status)


class ConfigurationError(InternalError):
    """Raised when application configuration is invalid."""

    def __init__(
        self,
        message: str = "Configuration error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="CONFIGURATION_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class DependencyError(InternalError):
    """Raised when a required dependency is unavailable."""

    def __init__(
        self,
        dependency: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "Dependency error"
        error_details = details or {}
        if dependency:
            message = f"Dependency unavailable: {dependency}"
            error_details["dependency"] = dependency
        super().__init__(
            message=message,
            error_code="DEPENDENCY_ERROR",
            details=error_details,
            http_status=HTTP_503_SERVICE_UNAVAILABLE,
        )


class MiddlewareError(InternalError):
    """Raised when middleware operation fails."""

    def __init__(
        self,
        message: str = "Middleware error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="MIDDLEWARE_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class InternalServerError(InternalError):
    """Raised when an unexpected internal error occurs."""

    def __init__(
        self,
        message: str = "Internal server error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="INTERNAL_SERVER_ERROR",
            details=details,
            http_status=HTTP_500_INTERNAL_SERVER_ERROR,
        )
