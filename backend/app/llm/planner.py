"""Analysis planner for converting natural language questions into AnalysisPlan objects.

This module is responsible for converting user questions into validated AnalysisPlan
objects that can be executed by the deterministic analytics executor. It does NOT
execute analytics, perform calculations, access DataFrames, or generate explanations.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

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
    build_dataset_context,
    build_planner_system_prompt,
    build_planner_user_prompt,
)
from app.schemas import (
    AggregationType,
    AllowedOperation,
    AnalysisPlan,
    ChartType,
    FilterOperator,
    SortOrder,
)

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    """Base exception for planner errors."""

    pass


class InvalidQuestionError(PlannerError):
    """Raised when the user question is invalid."""

    pass


class InvalidDatasetProfileError(PlannerError):
    """Raised when the dataset profile is invalid."""

    pass


class PlanningError(PlannerError):
    """Raised when planning fails due to LLM or validation issues."""

    pass


class AnalysisPlanner:
    """Converts natural language questions into validated AnalysisPlan objects.

    The planner uses an LLM to understand user intent and generate structured
    analysis plans. It validates all plans before returning them to ensure
    they can be safely executed by the analytics executor.

    The planner is designed to be testable and extensible, with dependency
    injection for the LLM client and clean separation of concerns.
    """

    def __init__(self, llm_client: BaseLLMClient) -> None:
        """Initialize the analysis planner.

        Args:
            llm_client: LLM client for generating analysis plans. Must implement
                BaseLLMClient interface. Injected via dependency injection.

        Raises:
            ValueError: If llm_client is None or does not implement BaseLLMClient.
        """
        if llm_client is None:
            raise ValueError("llm_client cannot be None.")

        if not isinstance(llm_client, BaseLLMClient):
            raise ValueError("llm_client must implement BaseLLMClient interface.")

        self._llm_client = llm_client

    def plan(
        self,
        user_question: str,
        dataset_profile: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> AnalysisPlan:
        """Convert a natural language question into a validated AnalysisPlan.

        Args:
            user_question: The user's natural language question about the dataset.
            dataset_profile: Dataset metadata from DatasetProfiler, including columns,
                types, sample rows, and statistics.
            conversation_history: Optional list of previous question/answer pairs
                for follow-up context. Each dict should have 'question' and 'answer' keys.

        Returns:
            A validated AnalysisPlan object that can be executed by the executor.

        Raises:
            InvalidQuestionError: If the question is empty or invalid.
            InvalidDatasetProfileError: If the dataset profile is malformed.
            PlanningError: If planning fails due to LLM or validation issues.
            AuthenticationError: If LLM authentication fails.
            RateLimitError: If LLM rate limit is exceeded.
            NetworkError: If network communication fails.
            TimeoutError: If LLM request times out.
            LLMError: For other LLM-related errors.
        """
        # Validate inputs
        self._validate_question(user_question)
        self._validate_dataset_profile(dataset_profile)

        # Prepare dataset context for the LLM
        dataset_context = self._prepare_dataset_context(dataset_profile)

        # Build prompts
        system_prompt = build_planner_system_prompt()
        user_prompt = self._prepare_prompt(user_question, dataset_context, conversation_history)

        try:
            # Call LLM to generate AnalysisPlan
            analysis_plan = self._llm_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=AnalysisPlan,
                temperature=0.3,  # Lower temperature for more deterministic planning
            )

            # Validate the generated plan
            return self._validate_analysis_plan(analysis_plan, dataset_profile)

        except (AuthenticationError, RateLimitError, NetworkError, TimeoutError) as exc:
            # Re-raise LLM client errors directly
            raise
        except (EmptyResponseError, InvalidResponseError, StructuredValidationError) as exc:
            # Convert LLM response errors to planning errors
            raise PlanningError(f"Failed to generate valid analysis plan: {exc}") from exc
        except LLMError as exc:
            # Convert other LLM errors to planning errors
            raise PlanningError(f"LLM error during planning: {exc}") from exc
        except Exception as exc:
            # Catch any unexpected errors
            self._handle_planner_error(exc)

    def _validate_question(self, question: str) -> None:
        """Validate the user question.

        Args:
            question: The user's natural language question.

        Raises:
            InvalidQuestionError: If the question is empty or contains only whitespace.
        """
        if not question:
            raise InvalidQuestionError("Question cannot be empty.")

        if not question.strip():
            raise InvalidQuestionError("Question cannot contain only whitespace.")

        if len(question.strip()) < 3:
            raise InvalidQuestionError("Question is too short.")

    def _validate_dataset_profile(self, profile: dict[str, Any]) -> None:
        """Validate the dataset profile structure.

        Args:
            profile: Dataset profile dictionary from DatasetProfiler.

        Raises:
            InvalidDatasetProfileError: If the profile is malformed or missing required fields.
        """
        if not isinstance(profile, dict):
            raise InvalidDatasetProfileError("Dataset profile must be a dictionary.")

        if not profile:
            raise InvalidDatasetProfileError("Dataset profile cannot be empty.")

        # Check for required top-level fields
        if "shape" not in profile:
            raise InvalidDatasetProfileError("Dataset profile missing 'shape' field.")

        if "columns" not in profile:
            raise InvalidDatasetProfileError("Dataset profile missing 'columns' field.")

        # Validate shape
        shape = profile["shape"]
        if not isinstance(shape, dict):
            raise InvalidDatasetProfileError("Dataset profile 'shape' must be a dictionary.")

        if "rows" not in shape or "columns" not in shape:
            raise InvalidDatasetProfileError("Dataset profile 'shape' missing 'rows' or 'columns'.")

        # Validate columns
        columns = profile["columns"]
        if not isinstance(columns, dict):
            raise InvalidDatasetProfileError("Dataset profile 'columns' must be a dictionary.")

        if not columns:
            raise InvalidDatasetProfileError("Dataset profile 'columns' cannot be empty.")

    def _prepare_dataset_context(self, profile: dict[str, Any]) -> str:
        """Prepare dataset context string for the LLM prompt.

        Args:
            profile: Dataset profile dictionary from DatasetProfiler.

        Returns:
            Formatted dataset context string.
        """
        # Extract column information
        columns_dict = profile.get("columns", {})
        column_names = list(columns_dict.keys())
        column_types = {}

        for col_name, col_metadata in columns_dict.items():
            semantic_type = col_metadata.get("semantic_type", "unknown")
            column_types[col_name] = semantic_type

        # Extract sample rows if available
        sample_rows = profile.get("sample_rows", [])

        # Extract row count
        shape = profile.get("shape", {})
        row_count = shape.get("rows")

        # Build context using prompts module
        return build_dataset_context(
            columns=column_names,
            column_types=column_types,
            sample_rows=sample_rows,
            row_count=row_count,
        )

    def _prepare_prompt(
        self,
        question: str,
        dataset_context: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """Prepare the user prompt for the LLM.

        Args:
            question: The user's natural language question.
            dataset_context: Formatted dataset context string.
            conversation_history: Optional conversation history for follow-up context.

        Returns:
            Complete user prompt string.
        """
        # Build base prompt
        user_prompt = build_planner_user_prompt(question, dataset_context)

        # Add conversation history if provided
        if conversation_history:
            history_section = self._build_conversation_context(conversation_history)
            user_prompt = f"{history_section}\n\n{user_prompt}"

        return user_prompt

    def _build_conversation_context(self, history: list[dict[str, str]]) -> str:
        """Build conversation context section for follow-up questions.

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

    def _validate_analysis_plan(
        self, plan: AnalysisPlan, dataset_profile: dict[str, Any]
    ) -> AnalysisPlan:
        """Validate the generated AnalysisPlan.

        Args:
            plan: The AnalysisPlan generated by the LLM.
            dataset_profile: Dataset profile for column validation.

        Returns:
            The validated AnalysisPlan.

        Raises:
            PlanningError: If the plan fails validation.
        """
        # Validate operation
        self._validate_operation(plan.operation)

        # Validate aggregation if present
        if plan.aggregation is not None:
            self._validate_aggregation(plan.aggregation)

        # Validate chart type
        self._validate_chart_type(plan.chart_type)

        # Validate target columns exist in dataset
        if plan.target_columns:
            self._validate_columns_exist(plan.target_columns, dataset_profile)

        # Validate group_by columns exist in dataset
        if plan.group_by:
            self._validate_columns_exist(plan.group_by, dataset_profile)

        # Validate sort_by column exists in dataset
        if plan.sort_by:
            self._validate_columns_exist([plan.sort_by], dataset_profile)

        # Validate filter columns exist in dataset
        if plan.filters:
            self._validate_filters(plan.filters, dataset_profile)

        # Validate sort order if sort_by is present
        if plan.sort_by and plan.sort_order is not None:
            self._validate_sort_order(plan.sort_order)

        # Validate operation-specific requirements
        self._validate_operation_requirements(plan)

        return plan

    def _validate_operation(self, operation: AllowedOperation) -> None:
        """Validate that the operation is a known allowed operation.

        Args:
            operation: The operation to validate.

        Raises:
            PlanningError: If the operation is unknown.
        """
        # Pydantic already validates this, but we double-check for safety
        if operation not in AllowedOperation:
            raise PlanningError(f"Unknown operation: {operation}")

    def _validate_aggregation(self, aggregation: AggregationType) -> None:
        """Validate that the aggregation is a known aggregation type.

        Args:
            aggregation: The aggregation to validate.

        Raises:
            PlanningError: If the aggregation is unknown.
        """
        # Pydantic already validates this, but we double-check for safety
        if aggregation not in AggregationType:
            raise PlanningError(f"Unknown aggregation: {aggregation}")

    def _validate_chart_type(self, chart_type: ChartType) -> None:
        """Validate that the chart type is a known chart type.

        Args:
            chart_type: The chart type to validate.

        Raises:
            PlanningError: If the chart type is unknown.
        """
        # Pydantic already validates this, but we double-check for safety
        if chart_type not in ChartType:
            raise PlanningError(f"Unknown chart type: {chart_type}")

    def _validate_columns_exist(
        self, columns: list[str], dataset_profile: dict[str, Any]
    ) -> None:
        """Validate that all specified columns exist in the dataset.

        Args:
            columns: List of column names to validate.
            dataset_profile: Dataset profile containing available columns.

        Raises:
            PlanningError: If any column does not exist in the dataset.
        """
        available_columns = set(dataset_profile.get("columns", {}).keys())
        missing_columns = [col for col in columns if col not in available_columns]

        if missing_columns:
            missing_str = ", ".join(missing_columns)
            raise PlanningError(f"Columns not found in dataset: {missing_str}")

    def _validate_filters(
        self, filters: list[Any], dataset_profile: dict[str, Any]
    ) -> None:
        """Validate filter conditions.

        Args:
            filters: List of filter conditions to validate.
            dataset_profile: Dataset profile for column validation.

        Raises:
            PlanningError: If filters are invalid.
        """
        available_columns = set(dataset_profile.get("columns", {}).keys())

        for filter_condition in filters:
            # Validate column exists
            column = getattr(filter_condition, "column", None)
            if column and column not in available_columns:
                raise PlanningError(f"Filter column not found in dataset: {column}")

            # Validate operator
            operator = getattr(filter_condition, "operator", None)
            if operator and operator not in FilterOperator:
                raise PlanningError(f"Unknown filter operator: {operator}")

    def _validate_sort_order(self, sort_order: SortOrder) -> None:
        """Validate that the sort order is a known sort order.

        Args:
            sort_order: The sort order to validate.

        Raises:
            PlanningError: If the sort order is unknown.
        """
        # Pydantic already validates this, but we double-check for safety
        if sort_order not in SortOrder:
            raise PlanningError(f"Unknown sort order: {sort_order}")

    def _validate_operation_requirements(self, plan: AnalysisPlan) -> None:
        """Validate operation-specific requirements.

        Args:
            plan: The AnalysisPlan to validate.

        Raises:
            PlanningError: If the plan fails operation-specific validation.
        """
        # aggregate and groupby require aggregation
        if plan.operation in {AllowedOperation.AGGREGATE, AllowedOperation.GROUPBY}:
            if plan.aggregation is None:
                raise PlanningError(
                    f"Operation '{plan.operation.value}' requires an aggregation function."
                )

        # groupby requires group_by columns
        if plan.operation == AllowedOperation.GROUPBY:
            if not plan.group_by:
                raise PlanningError(
                    f"Operation '{plan.operation.value}' requires group_by columns."
                )

        # top_n requires sort_by and limit
        if plan.operation == AllowedOperation.TOP_N:
            if plan.sort_by is None:
                raise PlanningError(
                    f"Operation '{plan.operation.value}' requires sort_by."
                )
            if plan.limit is None:
                raise PlanningError(
                    f"Operation '{plan.operation.value}' requires a limit."
                )

        # correlation requires target columns
        if plan.operation == AllowedOperation.CORRELATION:
            if not plan.target_columns:
                raise PlanningError(
                    f"Operation '{plan.operation.value}' requires target columns."
                )

    def _handle_planner_error(self, exc: Exception) -> None:
        """Handle unexpected planner errors.

        Args:
            exc: The unexpected exception.

        Raises:
            PlanningError: Always raises a PlanningError with descriptive message.
        """
        logger.error(f"Unexpected planner error: {exc}", exc_info=True)
        raise PlanningError(f"Unexpected error during planning: {exc}") from exc
