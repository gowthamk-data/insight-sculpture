"""Streaming API endpoint for real-time analysis progress updates.

This module is responsible ONLY for streaming analysis responses to the frontend
using Server-Sent Events (SSE). It does NOT perform analytics, generate AnalysisPlans,
execute Pandas, call OpenAI directly, or duplicate analyze.py logic. It only streams
progress and explanation text to the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
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
    get_llm_client,
    get_planner,
    get_session_manager,
)
from app.core.exceptions import ColumnNotFoundError
from app.executor import DataExecutor, ExecutionResult
from app.llm.client import (
    AuthenticationError,
    LLMError,
    NetworkError,
    RateLimitError,
    TimeoutError,
)
from app.llm.openai_client import BaseLLMClient
from app.llm.planner import (
    AnalysisPlanner,
    InvalidDatasetProfileError,
    InvalidQuestionError,
    PlanningError,
)
from app.llm.prompts import build_explainer_system_prompt, build_explainer_user_prompt
from app.session import DatasetSessionManager

logger = logging.getLogger(__name__)


class StreamRequest(BaseModel):
    """Request model for the stream endpoint."""

    session_id: str = Field(..., min_length=1, description="Active analytics session identifier.")
    question: str = Field(..., min_length=1, description="Natural-language question about the dataset.")
    conversation_history: list[dict[str, str]] | None = Field(
        default=None,
        description="Optional conversation history for follow-up context.",
    )


router = APIRouter(prefix="/stream", tags=["stream"])


@router.post("/", response_class=StreamingResponse)
async def stream_analysis(
    request: StreamRequest,
    session_manager: DatasetSessionManager = Depends(get_session_manager),
    planner: AnalysisPlanner = Depends(get_planner),
    executor: DataExecutor = Depends(get_executor),
    chart_builder: ChartBuilder = Depends(get_chart_builder),
    llm_client: BaseLLMClient = Depends(get_llm_client),
) -> StreamingResponse:
    """Stream analysis progress and explanation using Server-Sent Events.

    This endpoint orchestrates the complete analytics workflow and streams
    real-time progress updates to the frontend via SSE.

    Args:
        request: The stream request containing session_id, question, and optional conversation_history.
        session_manager: DatasetSessionManager instance (dependency injection).
        planner: AnalysisPlanner instance (dependency injection).
        executor: DataExecutor instance (dependency injection).
        chart_builder: ChartBuilder instance (dependency injection).
        llm_client: LLM client for streaming explanation (dependency injection).

    Returns:
        StreamingResponse with SSE events for analysis progress and explanation.
    """
    return StreamingResponse(
        _stream_analysis_generator(
            request=request,
            session_manager=session_manager,
            planner=planner,
            executor=executor,
            chart_builder=chart_builder,
            llm_client=llm_client,
        ),
        media_type="text/event-stream",
    )


async def _stream_analysis_generator(
    request: StreamRequest,
    session_manager: DatasetSessionManager,
    planner: AnalysisPlanner,
    executor: DataExecutor,
    chart_builder: ChartBuilder,
    llm_client: BaseLLMClient,
) -> AsyncGenerator[str, None]:
    """Async generator for streaming analysis progress via SSE.

    Args:
        request: The stream request.
        session_manager: DatasetSessionManager instance.
        planner: AnalysisPlanner instance.
        executor: DataExecutor instance.
        chart_builder: ChartBuilder instance.
        llm_client: LLM client for streaming.

    Yields:
        SSE-formatted event strings.
    """
    try:
        # Step 1: Validate session exists
        try:
            session = session_manager.get_session(request.session_id)
        except KeyError as exc:
            yield _format_sse_event("error", {"message": f"Session not found: {request.session_id}"})
            return

        # Step 2: Retrieve dataset profile
        try:
            dataset_profile = session_manager.get_profile(request.session_id)
        except KeyError as exc:
            yield _format_sse_event("error", {"message": f"Dataset profile not found for session: {request.session_id}"})
            return

        # Send connected event
        yield _format_sse_event("connected", {"session_id": request.session_id})

        # Step 3: Planning
        yield _format_sse_event("planning_started", {"question": request.question})

        try:
            analysis_plan = await asyncio.to_thread(
                planner.plan,
                user_question=request.question,
                dataset_profile=dataset_profile,
                conversation_history=request.conversation_history,
            )
        except InvalidQuestionError as exc:
            yield _format_sse_event("error", {"message": f"Invalid question: {exc}"})
            return
        except InvalidDatasetProfileError as exc:
            yield _format_sse_event("error", {"message": f"Invalid dataset profile: {exc}"})
            return
        except ColumnNotFoundError as exc:
            yield _format_sse_event("error", {"message": str(exc)})
            return
        except PlanningError as exc:
            yield _format_sse_event("error", {"message": f"Planning failed: {exc}"})
            return
        except AuthenticationError as exc:
            yield _format_sse_event("error", {"message": "LLM authentication failed."})
            return
        except RateLimitError as exc:
            yield _format_sse_event("error", {"message": "LLM rate limit exceeded."})
            return
        except NetworkError as exc:
            yield _format_sse_event("error", {"message": "Failed to connect to LLM provider."})
            return
        except TimeoutError as exc:
            yield _format_sse_event("error", {"message": "LLM request timed out."})
            return
        except LLMError as exc:
            yield _format_sse_event("error", {"message": f"LLM error during planning: {exc}"})
            return
        except Exception as exc:
            logger.error(f"Unexpected planning error: {exc}", exc_info=True)
            yield _format_sse_event("error", {"message": "Unexpected error during planning."})
            return

        yield _format_sse_event(
            "planning_completed",
            {"operation": analysis_plan.operation.value, "chart_type": analysis_plan.chart_type.value},
        )

        # Step 4: Execution
        yield _format_sse_event("execution_started", {"operation": analysis_plan.operation.value})

        try:
            execution_result = await asyncio.to_thread(
                executor.execute,
                session_id=request.session_id,
                plan=analysis_plan,
            )
        except KeyError as exc:
            yield _format_sse_event("error", {"message": f"Session not found during execution: {request.session_id}"})
            return
        except ValueError as exc:
            yield _format_sse_event("error", {"message": f"Execution failed: {exc}"})
            return
        except Exception as exc:
            logger.error(f"Unexpected execution error: {exc}", exc_info=True)
            yield _format_sse_event("error", {"message": "Failed to execute analysis plan."})
            return

        yield _format_sse_event(
            "execution_completed",
            {
                "rows_returned": execution_result.rows_returned,
                "columns_returned": execution_result.columns_returned,
                "execution_time_ms": execution_result.execution_time_ms,
            },
        )

        # Step 5: Chart generation
        yield _format_sse_event("chart_started", {"chart_type": execution_result.chart_recommendation})

        chart_data: dict[str, Any] | None = None
        try:
            chart_result = await asyncio.to_thread(chart_builder.build_chart, execution_result)
            chart_data = _serialize_chart_result(chart_result)
        except InvalidExecutionResultError as exc:
            logger.warning(f"Chart generation failed due to invalid execution result: {exc}")
        except UnsupportedChartTypeError as exc:
            logger.debug(f"No chart available: {exc}")
        except EmptyDatasetError as exc:
            logger.warning(f"Cannot generate chart from empty dataset: {exc}")
        except MissingColumnError as exc:
            logger.warning(f"Cannot generate chart due to missing columns: {exc}")
        except ChartBuilderError as exc:
            logger.warning(f"Chart generation failed: {exc}")
        except Exception as exc:
            logger.error(f"Unexpected chart error: {exc}", exc_info=True)

        yield _format_sse_event(
            "chart_completed",
            {"chart_generated": chart_data is not None, "chart_data": chart_data},
        )

        # Step 6: Explanation streaming
        yield _format_sse_event("explanation_started", {})

        try:
            # Prepare prompts for streaming explanation
            result_summary = _prepare_result_summary(execution_result)
            operation = execution_result.metadata.get("operation", "unknown")
            system_prompt = build_explainer_system_prompt()
            user_prompt = build_explainer_user_prompt(
                question=request.question,
                operation=operation,
                result_summary=result_summary,
            )

            # Stream explanation tokens
            full_explanation = ""
            async for token in _stream_text_async(llm_client, system_prompt, user_prompt):
                full_explanation += token
                yield _format_sse_event("token", {"token": token})

            # Send completed event with final results
            yield _format_sse_event(
                "completed",
                {
                    "explanation": full_explanation,
                    "rows_returned": execution_result.rows_returned,
                    "columns_returned": execution_result.columns_returned,
                    "chart_generated": chart_data is not None,
                    "processing_timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        except AuthenticationError as exc:
            yield _format_sse_event("error", {"message": "LLM authentication failed during explanation."})
            return
        except RateLimitError as exc:
            yield _format_sse_event("error", {"message": "LLM rate limit exceeded during explanation."})
            return
        except NetworkError as exc:
            yield _format_sse_event("error", {"message": "Failed to connect to LLM provider during explanation."})
            return
        except TimeoutError as exc:
            yield _format_sse_event("error", {"message": "LLM request timed out during explanation."})
            return
        except LLMError as exc:
            yield _format_sse_event("error", {"message": f"LLM error during explanation: {exc}"})
            return
        except Exception as exc:
            logger.error(f"Unexpected explanation error: {exc}", exc_info=True)
            yield _format_sse_event("error", {"message": "Unexpected error during explanation."})
            return

    except Exception as exc:
        # Catch any unexpected errors in the generator
        logger.error(f"Unexpected stream generator error: {exc}", exc_info=True)
        yield _format_sse_event("error", {"message": "Unexpected error during streaming."})


async def _stream_text_async(
    llm_client: BaseLLMClient,
    system_prompt: str,
    user_prompt: str,
) -> AsyncGenerator[str, None]:
    """Async wrapper for LLM text streaming.

    Args:
        llm_client: LLM client instance.
        system_prompt: System prompt for the LLM.
        user_prompt: User prompt for the LLM.

    Yields:
        Text chunks from the LLM.
    """
    # Run the synchronous stream_text in a thread pool
    loop = asyncio.get_event_loop()

    def _stream_sync():
        return llm_client.stream_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.5,
        )

    stream = await loop.run_in_executor(None, _stream_sync)

    while True:
        try:
            token = await loop.run_in_executor(None, next, stream)
            yield token
        except StopIteration:
            break


def _format_sse_event(event_name: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event.

    Args:
        event_name: The name of the SSE event.
        data: The data payload for the event.

    Returns:
        Formatted SSE event string.
    """
    data_json = json.dumps(data)
    return f"event: {event_name}\ndata: {data_json}\n\n"


def _prepare_result_summary(execution_result: ExecutionResult) -> str:
    """Prepare a formatted summary of the execution result for the LLM.

    Args:
        execution_result: The execution result.

    Returns:
        Formatted summary string.
    """
    sections = []
    sections.append(f"**Rows Returned**: {execution_result.rows_returned}")
    sections.append(f"**Columns Returned**: {execution_result.columns_returned}")

    summary = execution_result.summary
    if summary:
        sections.append("\n**Summary Statistics**:")
        for key, value in summary.items():
            if isinstance(value, (dict, list)):
                sections.append(f"- {key}: {_format_value(value)}")
            else:
                sections.append(f"- {key}: {value}")

    dataframe = getattr(execution_result, "dataframe", None)
    if dataframe is not None and hasattr(dataframe, "empty") and not dataframe.empty:
        sections.append("\n**Result Sample**:")
        for _, row in dataframe.head(5).iterrows():
            row_items = [f"{col}={_format_value(value)}" for col, value in row.items()]
            sections.append(f"- {', '.join(row_items)}")

    if hasattr(execution_result, "chart_recommendation"):
        sections.append(f"\n**Chart Recommendation**: {execution_result.chart_recommendation}")

    if hasattr(execution_result, "execution_time_ms"):
        sections.append(f"**Execution Time**: {execution_result.execution_time_ms:.2f}ms")

    return "\n".join(sections)


def _format_value(value: Any) -> str:
    """Format a value for display in the summary.

    Args:
        value: The value to format.

    Returns:
        Formatted string representation.
    """
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    if isinstance(value, list):
        if len(value) <= 5:
            return ", ".join(str(v) for v in value)
        return f"[{', '.join(str(v) for v in value[:3])}, ... ({len(value)} total)]"
    return str(value)


def _serialize_chart_result(chart_result: Any) -> dict[str, Any]:
    """Serialize a ChartResult to a JSON-serializable dictionary.

    Args:
        chart_result: The ChartResult to serialize.

    Returns:
        Formatted chart data dictionary.
    """
    return {
        "chart_type": chart_result.chart_type,
        "title": chart_result.title,
        "description": chart_result.description,
        "x_axis": chart_result.x_axis,
        "y_axis": chart_result.y_axis,
        "figure": chart_result.figure.to_json(),
        "metadata": chart_result.metadata,
    }
