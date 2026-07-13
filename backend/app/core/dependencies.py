"""Centralized dependency injection for Insight Sculpture.

This module provides reusable dependency providers for the entire application.
It is the ONLY place responsible for constructing and providing shared application services.

It performs NO analytics, NO Pandas execution, NO LLM calls, NO business logic.
Its only responsibility is dependency creation, lifetime management, and injection.

Security: Never exposes API keys, provider configuration, or internal details.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.analytics.chart_builder import ChartBuilder
from app.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    ConfigurationError,
    DependencyError,
    ProviderConfigurationError,
)
from app.executor import DataExecutor
from app.llm.openai_client import BaseLLMClient, OpenAIClient
from app.llm.planner import AnalysisPlanner
from app.llm.prompts import build_dataset_context
from app.profiler import DatasetProfiler
from app.session import DatasetSessionManager

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================


@lru_cache
def get_settings_cached():
    """Get cached application settings.

    This is a wrapper around config.get_settings() that provides
    a cached instance for dependency injection.

    Returns:
        Cached Settings instance.
    """
    return get_settings()


# ============================================================
# Session Management
# ============================================================


@lru_cache
def get_session_manager() -> DatasetSessionManager:
    """Get or create the shared dataset session manager.

    The session manager is a singleton that manages in-memory dataset sessions.
    It is reused across all requests to avoid recreating the manager.

    Returns:
        Shared DatasetSessionManager instance.

    Raises:
        DependencyError: If session manager initialization fails.
    """
    try:
        return DatasetSessionManager()
    except Exception as exc:
        logger.error(f"Failed to initialize session manager: {exc}", exc_info=True)
        raise DependencyError("session_manager") from exc


# ============================================================
# Dataset Profiling
# ============================================================


@lru_cache
def get_dataset_profiler() -> DatasetProfiler:
    """Get or create the shared dataset profiler.

    The profiler is a singleton that generates dataset metadata.
    It is reused across all requests to avoid recreating the profiler.

    Returns:
        Shared DatasetProfiler instance.

    Raises:
        DependencyError: If profiler initialization fails.
    """
    try:
        return DatasetProfiler()
    except Exception as exc:
        logger.error(f"Failed to initialize dataset profiler: {exc}", exc_info=True)
        raise DependencyError("dataset_profiler") from exc


# ============================================================
# Analytics Executor
# ============================================================


@lru_cache
def get_executor() -> DataExecutor:
    """Get or create the shared analytics executor.

    The executor is a singleton that runs validated AnalysisPlan objects.
    It is reused across all requests to avoid recreating the executor.

    Returns:
        Shared DataExecutor instance.

    Raises:
        DependencyError: If executor initialization fails.
    """
    try:
        return DataExecutor(
            session_manager=get_session_manager()
        )
    except Exception as exc:
        logger.error(
            f"Failed to initialize executor: {exc}",
            exc_info=True,
        )
        raise DependencyError("executor") from exc


# ============================================================
# Chart Builder
# ============================================================


@lru_cache
def get_chart_builder() -> ChartBuilder:
    """Get or create the shared chart builder.

    The chart builder is a singleton that generates Plotly charts.
    It is reused across all requests to avoid recreating the builder.

    Returns:
        Shared ChartBuilder instance.

    Raises:
        DependencyError: If chart builder initialization fails.
    """
    try:
        return ChartBuilder()
    except Exception as exc:
        logger.error(f"Failed to initialize chart builder: {exc}", exc_info=True)
        raise DependencyError("chart_builder") from exc


# ============================================================
# LLM Client
# ============================================================


@lru_cache
def get_llm_client() -> BaseLLMClient:
    """Get or create the shared LLM client.

    The LLM client is a singleton that communicates with the configured
    LLM provider (OpenAI or Anthropic). It is reused across all requests
    to avoid recreating the client and its underlying connections.

    Returns:
        Shared BaseLLMClient instance (OpenAIClient implementation).

    Raises:
        ProviderConfigurationError: If LLM provider is misconfigured.
        AuthenticationError: If API key is missing or invalid.
        DependencyError: If client initialization fails.
    """
    try:
        settings = get_settings_cached()

        # Validate API key is present
        if not settings.active_api_key:
            raise AuthenticationError(
                provider=settings.llm_provider.value,
                details={"reason": "API key not configured"},
            )

        # Create appropriate client based on provider
        if settings.llm_provider.value == "openai":
            return OpenAIClient(
                api_key=settings.openai_api_key,
                model=None,  # Use default or environment variable
                timeout=None,  # Use default timeout
            )
        elif settings.llm_provider.value == "anthropic":
            # Anthropic client will be added when needed
            raise ProviderConfigurationError(
                details={"provider": "anthropic", "reason": "Not yet implemented"}
            )
        else:
            raise ProviderConfigurationError(
                details={"provider": settings.llm_provider.value, "reason": "Unknown provider"}
            )

    except AuthenticationError:
        # Re-raise authentication errors directly
        raise
    except ProviderConfigurationError:
        # Re-raise configuration errors directly
        raise
    except Exception as exc:
        logger.error(f"Failed to initialize LLM client: {exc}", exc_info=True)
        raise DependencyError("llm_client") from exc


# ============================================================
# Analysis Planner
# ============================================================


def get_planner(llm_client: BaseLLMClient) -> AnalysisPlanner:
    """Get an analysis planner with the provided LLM client.

    The planner converts natural language questions into validated
    AnalysisPlan objects. It uses dependency injection for the LLM client.

    Note: This function is NOT cached because it receives the LLM client
    as a parameter. The LLM client itself is cached via get_llm_client().

    Args:
        llm_client: LLM client for generating analysis plans. Must implement
            BaseLLMClient interface.

    Returns:
        AnalysisPlanner instance.

    Raises:
        DependencyError: If planner initialization fails.
    """
    try:
        return AnalysisPlanner(llm_client=llm_client)
    except Exception as exc:
        logger.error(f"Failed to initialize planner: {exc}", exc_info=True)
        raise DependencyError("planner") from exc


# ============================================================
# Analysis Explainer
# ============================================================


def get_explainer(llm_client: BaseLLMClient):
    """Get an analysis explainer with the provided LLM client.

    The explainer converts execution results into natural-language explanations.
    It uses dependency injection for the LLM client.

    Note: This function is NOT cached because it receives the LLM client
    as a parameter. The LLM client itself is cached via get_llm_client().

    Args:
        llm_client: LLM client for generating explanations. Must implement
            BaseLLMClient interface.

    Returns:
        AnalysisExplainer instance.

    Raises:
        DependencyError: If explainer initialization fails.
    """
    try:
        from app.llm.explainer import AnalysisExplainer
        return AnalysisExplainer(llm_client=llm_client)
    except Exception as exc:
        logger.error(f"Failed to initialize explainer: {exc}", exc_info=True)
        raise DependencyError("explainer") from exc


# ============================================================
# Helper Functions
# ============================================================


def validate_dependencies() -> bool:
    """Validate that all critical dependencies can be initialized.

    This function is useful for health checks and startup validation.
    It attempts to initialize each dependency and returns True if all succeed.

    Returns:
        True if all dependencies can be initialized, False otherwise.
    """
    dependencies_valid = True

    # Validate session manager
    try:
        get_session_manager()
    except Exception as exc:
        logger.error(f"Session manager validation failed: {exc}")
        dependencies_valid = False

    # Validate dataset profiler
    try:
        get_dataset_profiler()
    except Exception as exc:
        logger.error(f"Dataset profiler validation failed: {exc}")
        dependencies_valid = False

    # Validate executor
    try:
        get_executor()
    except Exception as exc:
        logger.error(f"Executor validation failed: {exc}")
        dependencies_valid = False

    # Validate chart builder
    try:
        get_chart_builder()
    except Exception as exc:
        logger.error(f"Chart builder validation failed: {exc}")
        dependencies_valid = False

    # Validate LLM client
    try:
        get_llm_client()
    except Exception as exc:
        logger.error(f"LLM client validation failed: {exc}")
        dependencies_valid = False

    return dependencies_valid


def clear_dependency_cache() -> None:
    """Clear all cached dependency instances.

    This function is primarily useful for testing to ensure fresh
    dependency instances between test cases. It should not be used
    in production under normal circumstances.

    Warning: This clears all cached instances, which may affect
    performance if called frequently.
    """
    get_settings_cached.cache_clear()
    get_session_manager.cache_clear()
    get_dataset_profiler.cache_clear()
    get_executor.cache_clear()
    get_chart_builder.cache_clear()
    get_llm_client.cache_clear()

    logger.debug("Dependency cache cleared")
