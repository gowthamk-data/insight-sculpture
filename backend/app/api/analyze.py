"""Analyze API endpoint for orchestrating the AI analytics workflow.

This module coordinates the complete analytics pipeline: planning, execution,
charting, and explanation. It does NOT contain business logic - it simply
orchestrates existing modules.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.analytics.chart_builder import (
    ChartBuilder,
    ChartBuilderError,
    EmptyDatasetError,
    InvalidExecutionResultError,
    MissingColumnError,
    UnsupportedChartTypeError,
)
from app.core.dependencies import (
    get_chart_builder,
    get_executor,
    get_explainer,
    get_planner,
    get_session_manager,
)
from app.executor import DataExecutor, ExecutionResult
from app.llm.client import (
    AuthenticationError,
    LLMError,
    NetworkError,
    RateLimitError,
    TimeoutError,
)
from app.llm.explainer import (
    AnalysisExplainer,
    ExplanationError,
    ExplanationResult,
    InvalidExecutionResultError as ExplainerInvalidExecutionResultError,
)
from app.llm.planner import (
    AnalysisPlanner,
    InvalidDatasetProfileError,
    InvalidQuestionError,
    PlanningError,
)
from app.llm.prompts import build_dataset_context
from app.session import DatasetSessionManager

logger = logging.getLogger(__name__)


class AnalyzeRequest(BaseModel):
    """Request model for the analyze endpoint."""

    session_id: str = Field(..., min_length=1, description="Active analytics session identifier.")
    question: str = Field(..., min_length=1, description="Natural-language question about the dataset.")
    conversation_history: list[dict[str, str]] | None = Field(
        default=None,
        description="Optional conversation history for follow-up context.",
    )


class AnalyzeResponse(BaseModel):
    """Response model for the analyze endpoint."""

    analysis_plan: dict[str, Any] = Field(..., description="The validated analysis plan.")
    execution_result: dict[str, Any] = Field(..., description="Results from analytics execution.")
    chart: dict[str, Any] | None = Field(None, description="Plotly chart data if generated.")
    explanation: dict[str, Any] = Field(..., description="Natural-language explanation of results.")
    processing_time_ms: float = Field(..., description="Total processing time in milliseconds.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata about the analysis.")


router = APIRouter(prefix="/analyze", tags=["analyze"])


@router.post(
    "/",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Bad request - invalid question or missing columns",
            "model": dict,
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "LLM authentication failed",
            "model": dict,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Session or dataset profile not found",
            "model": dict,
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Validation error - invalid dataset profile or analysis plan",
            "model": dict,
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "LLM rate limit exceeded",
            "model": dict,
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Internal server error",
            "model": dict,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Service unavailable - LLM provider connection failed",
            "model": dict,
        },
    },
)
async def analyze(
    request: AnalyzeRequest,
    session_manager: DatasetSessionManager = Depends(get_session_manager),
    planner: AnalysisPlanner = Depends(get_planner),
    executor: DataExecutor = Depends(get_executor),
    chart_builder: ChartBuilder = Depends(get_chart_builder),
    explainer: AnalysisExplainer = Depends(get_explainer),
) -> AnalyzeResponse:
    """Analyze a dataset using AI-powered analytics.

    This endpoint orchestrates the complete analytics workflow:
    1. Validates the session exists
    2. Retrieves the dataset profile
    3. Calls the planner to generate an AnalysisPlan
    4. Executes the plan using the executor
    5. Generates a chart using the chart builder
    6. Generates an explanation using the explainer
    7. Returns a structured response with all components

    Args:
        request: The analyze request containing session_id, question, and optional conversation_history.
        session_manager: DatasetSessionManager instance (dependency injection).
        planner: AnalysisPlanner instance (dependency injection).
        executor: DataExecutor instance (dependency injection).
        chart_builder: ChartBuilder instance (dependency injection).
        explainer: AnalysisExplainer instance (dependency injection).

    Returns:
        AnalyzeResponse containing the analysis plan, execution result, chart, explanation, and metadata.

    Raises:
        HTTPException: For validation errors, session not found, missing columns, or processing failures.
    """
    start_time = time.perf_counter()

    # Validate session exists
    try:
        session = session_manager.get_session(request.session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {request.session_id}",
        ) from exc

    # Retrieve dataset profile
    try:
        dataset_profile = session_manager.get_profile(request.session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset profile not found for session: {request.session_id}",
        ) from exc

    # Step 1: Generate analysis plan
    try:
        analysis_plan = planner.plan(
            user_question=request.question,
            dataset_profile=dataset_profile,
            conversation_history=request.conversation_history,
        )
    except InvalidQuestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid question: {exc}",
        ) from exc
    except InvalidDatasetProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid dataset profile: {exc}",
        ) from exc
    except PlanningError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Planning failed: {exc}",
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="LLM authentication failed.",
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM rate limit exceeded.",
        ) from exc
    except NetworkError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to connect to LLM provider.",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM request timed out.",
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM error during planning: {exc}",
        ) from exc

    # Step 2: Execute analysis plan
    try:
        execution_result = executor.execute(
            session_id=request.session_id,
            plan=analysis_plan,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found during execution: {request.session_id}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Execution failed: {exc}",
        ) from exc
    except Exception as exc:
        logger.error(f"Unexpected execution error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute analysis plan.",
        ) from exc

    # Step 3: Generate chart
    chart_data: dict[str, Any] | None = None
    try:
        chart_result = chart_builder.build_chart(execution_result)
        chart_data = _serialize_chart_result(chart_result)
    except InvalidExecutionResultError as exc:
        # Chart generation failure should not fail the entire request
        logger.warning(f"Chart generation failed due to invalid execution result: {exc}")
    except UnsupportedChartTypeError as exc:
        # No chart available for this result type
        logger.debug(f"No chart available: {exc}")
    except EmptyDatasetError as exc:
        # Dataset is empty, cannot generate chart
        logger.warning(f"Cannot generate chart from empty dataset: {exc}")
    except MissingColumnError as exc:
        # Required columns missing, cannot generate chart
        logger.warning(f"Cannot generate chart due to missing columns: {exc}")
    except ChartBuilderError as exc:
        # Other chart builder errors
        logger.warning(f"Chart generation failed: {exc}")
    except Exception as exc:
        # Unexpected chart errors
        logger.error(f"Unexpected chart error: {exc}", exc_info=True)

    # Step 4: Generate explanation
    dataset_context = build_dataset_context(
        columns=list(dataset_profile.get("columns", {}).keys()),
        column_types={
            col: meta.get("semantic_type", "unknown")
            for col, meta in dataset_profile.get("columns", {}).items()
        },
        sample_rows=dataset_profile.get("sample_rows"),
        row_count=dataset_profile.get("shape", {}).get("rows"),
    )
    try:
        explanation_result = explainer.explain(
            original_question=request.question,
            execution_result=execution_result,
            conversation_history=request.conversation_history,
            dataset_context=dataset_context,
        )
        explanation_data = _serialize_explanation_result(explanation_result)
    except ExplainerInvalidExecutionResultError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid execution result for explanation: {exc}",
        ) from exc
    except ExplanationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Explanation generation failed: {exc}",
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="LLM authentication failed during explanation.",
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM rate limit exceeded during explanation.",
        ) from exc
    except NetworkError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to connect to LLM provider during explanation.",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM request timed out during explanation.",
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM error during explanation: {exc}",
        ) from exc

    # Calculate total processing time
    processing_time_ms = (time.perf_counter() - start_time) * 1000

    # Build metadata
    metadata = {
        "session_id": request.session_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "operation": analysis_plan.operation.value,
        "chart_generated": chart_data is not None,
    }

    # Serialize analysis plan
    analysis_plan_data = analysis_plan.model_dump(mode="json")

    # Serialize execution result
    execution_result_data = _serialize_execution_result(execution_result)

    return AnalyzeResponse(
        analysis_plan=analysis_plan_data,
        execution_result=execution_result_data,
        chart=chart_data,
        explanation=explanation_data,
        processing_time_ms=processing_time_ms,
        metadata=metadata,
    )


def _serialize_execution_result(execution_result: ExecutionResult) -> dict[str, Any]:
    """Serialize an ExecutionResult to a JSON-serializable dictionary.

    Args:
        execution_result: The ExecutionResult to serialize.

    Returns:
        A JSON-serializable dictionary.
    """
    return {
        "rows_returned": execution_result.rows_returned,
        "columns_returned": execution_result.columns_returned,
        "execution_time_ms": execution_result.execution_time_ms,
        "chart_recommendation": execution_result.chart_recommendation,
        "summary": execution_result.summary,
        "metadata": execution_result.metadata,
    }


def _serialize_chart_result(chart_result: Any) -> dict[str, Any]:
    """Serialize a ChartResult to a JSON-serializable dictionary.

    Args:
        chart_result: The ChartResult to serialize.

    Returns:
        A JSON-serializable dictionary.
    """
    # Convert Plotly figure to JSON
    figure_json = chart_result.figure.to_json()

    return {
        "chart_type": chart_result.chart_type,
        "title": chart_result.title,
        "description": chart_result.description,
        "x_axis": chart_result.x_axis,
        "y_axis": chart_result.y_axis,
        "figure": figure_json,
        "metadata": chart_result.metadata,
    }


def _serialize_explanation_result(explanation_result: ExplanationResult) -> dict[str, Any]:
    """Serialize an ExplanationResult to a JSON-serializable dictionary.

    Args:
        explanation_result: The ExplanationResult to serialize.

    Returns:
        A JSON-serializable dictionary.
    """
    return {
        "explanation": explanation_result.explanation,
        "summary": explanation_result.summary,
        "key_findings": explanation_result.key_findings,
        "suggested_follow_up_questions": explanation_result.suggested_follow_up_questions,
        "confidence": explanation_result.confidence,
        "metadata": explanation_result.metadata,
    }
