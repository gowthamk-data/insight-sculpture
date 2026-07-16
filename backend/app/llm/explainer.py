"""Analysis explainer for converting execution results into natural-language explanations.

This module is responsible for converting verified execution results into clear,
accurate, human-readable explanations. It does NOT perform calculations, execute
analytics, access datasets, or generate AnalysisPlans.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.llm.client import (
    AuthenticationError,
    EmptyResponseError,
    InvalidResponseError,
    LLMError,
    NetworkError,
    RateLimitError,
    StructuredValidationError,
    TimeoutError,
)
from app.llm.openai_client import BaseLLMClient
from app.llm.prompts import (
    build_explainer_system_prompt,
    build_explainer_user_prompt,
)

logger = logging.getLogger(__name__)


class ExplainerError(Exception):
    """Base exception for explainer errors."""

    pass


class InvalidExecutionResultError(ExplainerError):
    """Raised when the execution result is invalid."""

    pass


class ExplanationError(ExplainerError):
    """Raised when explanation generation fails."""

    pass


@dataclass
class ExplanationResult:
    """Structured result from the analysis explainer.

    Contains the natural-language explanation along with structured metadata
    for downstream consumption.
    """

    explanation: str
    """The main natural-language explanation of the results."""

    summary: str
    """A concise summary of the key findings."""

    key_findings: list[str]
    """Important observations extracted from the execution result."""

    suggested_follow_up_questions: list[str]
    """Suggested follow-up questions for the user."""

    confidence: str
    """Confidence level in the explanation (high, medium, low)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the explanation."""


class ExplanationResponse(BaseModel):
    """Pydantic model for structured LLM explanation output."""

    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    explanation: str = Field(
        ...,
        description="The main natural-language explanation of the results.",
    )
    summary: str = Field(
        ...,
        description="A concise summary of the key findings.",
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Important observations extracted from the execution result.",
    )
    suggested_follow_up_questions: list[str] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3-5 suggested follow-up questions for the user.",
    )
    confidence: str = Field(
        ...,
        description="Confidence level: high, medium, or low.",
    )


class AnalysisExplainer:
    """Converts execution results into natural-language explanations.

    The explainer uses an LLM to interpret verified analytics results and
    produce clear, accessible explanations for users. It is designed to be
    testable and extensible, with dependency injection for the LLM client.
    """

    def __init__(self, llm_client: BaseLLMClient) -> None:
        """Initialize the analysis explainer.

        Args:
            llm_client: LLM client for generating explanations. Must implement
                BaseLLMClient interface. Injected via dependency injection.

        Raises:
            ValueError: If llm_client is None or does not implement BaseLLMClient.
        """
        if llm_client is None:
            raise ValueError("llm_client cannot be None.")

        if not isinstance(llm_client, BaseLLMClient):
            raise ValueError("llm_client must implement BaseLLMClient interface.")

        self._llm_client = llm_client

    def explain(
        self,
        original_question: str,
        execution_result: Any,
        conversation_history: list[dict[str, str]] | None = None,
        dataset_context: str | None = None,
    ) -> ExplanationResult:
        """Convert execution results into a natural-language explanation.

        Args:
            original_question: The user's original question.
            execution_result: ExecutionResult from the analytics executor.
            conversation_history: Optional list of previous question/answer pairs
                for follow-up context. Each dict should have 'question' and 'answer' keys.
            dataset_context: Optional formatted dataset context string for grounding.

        Returns:
            An ExplanationResult containing the explanation and structured metadata.

        Raises:
            InvalidExecutionResultError: If the execution result is invalid.
            ExplanationError: If explanation generation fails.
            AuthenticationError: If LLM authentication fails.
            RateLimitError: If LLM rate limit is exceeded.
            NetworkError: If network communication fails.
            TimeoutError: If LLM request times out.
            LLMError: For other LLM-related errors.
        """
        # Validate execution result
        self._validate_execution_result(execution_result)

        # Prepare result summary for the LLM
        result_summary = self._prepare_result_summary(execution_result)

        # Extract operation from metadata
        operation = self._extract_operation(execution_result)

        # Build prompts
        system_prompt = build_explainer_system_prompt()
        user_prompt = self._prepare_prompt(
            original_question, operation, result_summary, conversation_history, dataset_context
        )
        
        logger.info("========== EXPLAINER SYSTEM PROMPT ==========")
        logger.info(system_prompt)

        logger.info("========== EXPLAINER USER PROMPT ==========")
        logger.info(user_prompt)

        logger.info("========== DATASET CONTEXT ==========")
        logger.info(dataset_context)

        try:
            # Call LLM to generate structured explanation
            explanation_response = self._llm_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=ExplanationResponse,
                temperature=0.1,
            )

            # Convert to ExplanationResult
            return self._build_explanation_result(
                explanation_response, execution_result
            )

        except (AuthenticationError, RateLimitError, NetworkError, TimeoutError) as exc:
            # Re-raise LLM client errors directly
            raise
        except (EmptyResponseError, InvalidResponseError, StructuredValidationError) as exc:
            # Convert LLM response errors to explanation errors
            raise ExplanationError(f"Failed to generate valid explanation: {exc}") from exc
        except LLMError as exc:
            # Convert other LLM errors to explanation errors
            raise ExplanationError(f"LLM error during explanation: {exc}") from exc
        except Exception as exc:
            # Catch any unexpected errors
            self._handle_explainer_error(exc)

    def _validate_execution_result(self, execution_result: Any) -> None:
        """Validate the execution result structure.

        Args:
            execution_result: ExecutionResult from the analytics executor.

        Raises:
            InvalidExecutionResultError: If the execution result is malformed.
        """
        if execution_result is None:
            raise InvalidExecutionResultError("Execution result cannot be None.")

        # Check for required attributes
        required_attrs = ["summary", "rows_returned", "columns_returned", "metadata"]
        for attr in required_attrs:
            if not hasattr(execution_result, attr):
                raise InvalidExecutionResultError(
                    f"Execution result missing required attribute: {attr}"
                )

        # Validate summary is a dictionary
        if not isinstance(execution_result.summary, dict):
            raise InvalidExecutionResultError("Execution result summary must be a dictionary.")

    def _prepare_result_summary(self, execution_result: Any) -> str:
        """Prepare a formatted summary of the execution result.

        Args:
            execution_result: ExecutionResult from the analytics executor.

        Returns:
            Formatted string summary for the LLM.
        """
        sections = []

        # Add basic statistics
        sections.append(f"**Rows Returned**: {execution_result.rows_returned}")
        sections.append(f"**Columns Returned**: {execution_result.columns_returned}")

        # Add summary information
        summary = execution_result.summary
        if summary:
            sections.append("\n**Summary Statistics**:")
            for key, value in summary.items():
                if isinstance(value, (dict, list)):
                    # Format complex structures
                    sections.append(f"- {key}: {self._format_value(value)}")
                else:
                    sections.append(f"- {key}: {value}")

        # Add a sample of the actual execution results to ground the explanation in real values
        dataframe = getattr(execution_result, "dataframe", None)
        if dataframe is not None and hasattr(dataframe, "empty") and not dataframe.empty:
            sections.append("\n**Result Sample**:")
            for _, row in dataframe.head(5).iterrows():
                row_items = [f"{col}={self._format_value(value)}" for col, value in row.items()]
                sections.append(f"- {', '.join(row_items)}")

        # Add chart recommendation
        if hasattr(execution_result, "chart_recommendation"):
            sections.append(f"\n**Chart Recommendation**: {execution_result.chart_recommendation}")

        # Add execution time
        if hasattr(execution_result, "execution_time_ms"):
            sections.append(f"**Execution Time**: {execution_result.execution_time_ms:.2f}ms")

        return "\n".join(sections)

    def _format_value(self, value: Any) -> str:
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

    def _extract_operation(self, execution_result: Any) -> str:
        """Extract the operation name from execution result metadata.

        Args:
            execution_result: ExecutionResult from the analytics executor.

        Returns:
            Operation name as a string.
        """
        metadata = execution_result.metadata if hasattr(execution_result, "metadata") else {}
        return metadata.get("operation", "unknown")

    def _prepare_prompt(
        self,
        original_question: str,
        operation: str,
        result_summary: str,
        conversation_history: list[dict[str, str]] | None = None,
        dataset_context: str | None = None,
    ) -> str:
        """Prepare the user prompt for the LLM.

        Args:
            original_question: The user's original question.
            operation: The analytics operation that was performed.
            result_summary: Formatted summary of execution results.
            conversation_history: Optional conversation history for follow-up context.
            dataset_context: Optional formatted dataset context string for grounding.

        Returns:
            Complete user prompt string.
        """
        # Build base prompt using prompts module
        user_prompt = build_explainer_user_prompt(
            question=original_question,
            operation=operation,
            result_summary=result_summary,
            dataset_context=dataset_context,
        )

        # Add conversation history if provided
        if conversation_history:
            history_section = self._build_conversation_context(conversation_history)
            user_prompt = f"{history_section}\n\n{user_prompt}"

        # Add instructions for structured output
        user_prompt += """

## Response Format

Output ONLY a valid JSON object. Do NOT include any text, markdown, code fences, or explanation outside the JSON object.

The JSON object must contain exactly these fields:
- explanation: The main natural-language explanation
- summary: A concise summary of key findings
- key_findings: List of important observations (3-5 items)
- suggested_follow_up_questions: List of 3-5 suggested follow-up questions
- confidence: One of "high", "medium", or "low"

Any text outside the JSON object will be rejected.
"""

        return user_prompt

    def _build_conversation_context(self, history: list[dict[str, str]]) -> str:
        """Build conversation context section for follow-up explanations.

        Args:
            history: List of previous question/answer pairs.

        Returns:
            Formatted conversation history string.
        """
        if not history:
            return ""

        sections = ["## Conversation History"]

        for i, turn in enumerate(history, 1):
            question = turn.get("question", "")
            answer = turn.get("answer", "")
            sections.append(f"\n**Turn {i}:**")
            sections.append(f"Question: {question}")
            sections.append(f"Answer: {answer}")

        return "\n".join(sections)

    def _build_explanation_result(
        self,
        explanation_response: ExplanationResponse,
        execution_result: Any,
    ) -> ExplanationResult:
        """Build an ExplanationResult from the LLM response.

        Args:
            explanation_response: Structured response from the LLM.
            execution_result: Original execution result for metadata.

        Returns:
            ExplanationResult with explanation and metadata.
        """
        # Build metadata
        metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rows_returned": execution_result.rows_returned,
            "columns_returned": execution_result.columns_returned,
        }

        if hasattr(execution_result, "execution_time_ms"):
            metadata["execution_time_ms"] = execution_result.execution_time_ms

        if hasattr(execution_result, "chart_recommendation"):
            metadata["chart_recommendation"] = execution_result.chart_recommendation

        return ExplanationResult(
            explanation=explanation_response.explanation,
            summary=explanation_response.summary,
            key_findings=explanation_response.key_findings,
            suggested_follow_up_questions=explanation_response.suggested_follow_up_questions,
            confidence=explanation_response.confidence,
            metadata=metadata,
        )

    def _handle_explainer_error(self, exc: Exception) -> None:
        """Handle unexpected explainer errors.

        Args:
            exc: The unexpected exception.

        Raises:
            ExplanationError: Always raises an ExplanationError with descriptive message.
        """
        logger.error(f"Unexpected explainer error: {exc}", exc_info=True)
        raise ExplanationError(f"Unexpected error during explanation: {exc}") from exc
