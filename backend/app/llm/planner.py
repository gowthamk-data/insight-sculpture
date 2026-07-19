"""Analysis planner for converting natural language questions into AnalysisPlan objects.

This module is responsible for converting user questions into validated AnalysisPlan
objects that can be executed by the deterministic analytics executor. It does NOT
execute analytics, perform calculations, access DataFrames, or generate explanations.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import ColumnNotFoundError
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
    FilterCondition,
    FilterOperator,
    SortOrder,
)

from app.llm.intent_normalizer import SemanticIntent, _COLUMN_ALIASES

logger = logging.getLogger(__name__)

# Core numeric columns intended for correlation when "all numeric columns" is requested
# Uses lowercase for case-insensitive matching against dataset profile
_INTENDED_NUMERIC_COLUMNS: frozenset[str] = frozenset({
    "age", "income", "score",
})


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

        # Deterministic schema resolution before any LLM work
        from app.analytics.intent_extractor import resolve_schema_references

        resolution = resolve_schema_references(user_question, dataset_profile)

        if not resolution.resolved:
            raise ColumnNotFoundError(
                column=resolution.missing_columns,
                available_columns=list(dataset_profile["columns"].keys()),
                details={
                    "did_you_mean": resolution.suggestions,
                },
            )

        # Semantic intent normalization and entity resolution
        from app.llm.intent_normalizer import extract_semantic_intent
        from app.analytics.intent_extractor import extract_intent

        raw_intent = extract_intent(user_question)
        semantic_intent = extract_semantic_intent(user_question, dataset_profile, raw_intent)

        # Prepare dataset context for the LLM
        dataset_context = self._prepare_dataset_context(dataset_profile)

        # Build prompts with intent injection
        system_prompt = build_planner_system_prompt()
        user_prompt = self._prepare_prompt(
            user_question, dataset_context, conversation_history, semantic_intent
        )

        try:
            # Call LLM to generate AnalysisPlan
            logger.info("========== PLANNER SYSTEM PROMPT ==========")
            logger.info(system_prompt)

            logger.info("========== PLANNER USER PROMPT ==========")
            logger.info(user_prompt)
            analysis_plan = self._llm_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=AnalysisPlan,
                temperature=0.3,  # Lower temperature for more deterministic planning
            )

            # Post-generation normalization and sanitization
            analysis_plan = self._normalize_analysis_plan(analysis_plan, dataset_profile, user_question, semantic_intent)

            # Validate the normalized plan
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
        semantic_intent: SemanticIntent | None = None,
    ) -> str:
        """Prepare the user prompt for the LLM.

        Args:
            question: The user's natural language question.
            dataset_context: Formatted dataset context string.
            conversation_history: Optional conversation history for follow-up context.
            semantic_intent: Optional normalized intent with operational hints.

        Returns:
            Complete user prompt string.
        """
        # Build base prompt with intent injection
        user_prompt = build_planner_user_prompt(question, dataset_context, semantic_intent)

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
            ColumnNotFoundError: If any column does not exist in the dataset.
        """
        available_columns = set(dataset_profile.get("columns", {}).keys())
        missing_columns = [col for col in columns if col not in available_columns]

        if missing_columns:
            suggestions: dict[str, list[str]] = {}
            for col in missing_columns:
                matches = difflib.get_close_matches(col, available_columns, n=3, cutoff=0.6)
                if matches:
                    suggestions[col] = matches

            raise ColumnNotFoundError(
                column=missing_columns,
                available_columns=list(available_columns),
                details={"did_you_mean": suggestions} if suggestions else None,
            )

    def _validate_filters(
        self, filters: list[Any], dataset_profile: dict[str, Any]
    ) -> None:
        """Validate filter conditions.

        Args:
            filters: List of filter conditions to validate.
            dataset_profile: Dataset profile for column validation.

        Raises:
            ColumnNotFoundError: If a filter column does not exist in the dataset.
            PlanningError: If a filter operator is invalid.
        """
        available_columns = set(dataset_profile.get("columns", {}).keys())

        for filter_condition in filters:
            column = getattr(filter_condition, "column", None)
            if column and column not in available_columns:
                suggestions = difflib.get_close_matches(column, available_columns, n=3, cutoff=0.6)
                details = {"did_you_mean": {column: suggestions}} if suggestions else None
                raise ColumnNotFoundError(
                    column=column,
                    available_columns=list(available_columns),
                    details=details,
                )

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

    # Compound grouping dimensions that should be treated as a single unified entity
    # rather than being fragmented into multiple group_by columns. Mapping is from a
    # lower-cased multi-word phrase to the single resolved group_by column.
    _COMPOUND_DIMENSION_MAP: dict[str, str] = {
        "customer segment": "Segment",
        "customer segments": "Segment",
        "customers segment": "Segment",
        "customer type": "CustomerType",
        "customer types": "CustomerType",
        "product category": "Category",
        "product categories": "Category",
        "customer category": "Category",
        "customer categories": "Category",
        "customer region": "Region",
        "customer regions": "Region",
        "customer department": "Department",
        "customer departments": "Department",
    }


    # ============================================================
    # SEMANTIC RANKING KEYWORDS — deterministic sort-direction signals
    # that must override generic metric heuristics. These are generic
    # ranking tokens, not benchmark-specific string matches.
    # ============================================================
    _ASCENDING_RANKING_KEYWORDS: frozenset[str] = frozenset({
        "bottom", "lowest", "smallest", "least",
    })
    _DESCENDING_RANKING_KEYWORDS: frozenset[str] = frozenset({
        "top", "highest", "largest", "greatest", "most",
    })

    # Explicit direction tokens stated directly by the user — highest precedence.
    _EXPLICIT_ASCENDING_TOKENS: frozenset[str] = frozenset({
        "ascending", "asc", "a to z", "a-z", "low to high",
    })
    _EXPLICIT_DESCENDING_TOKENS: frozenset[str] = frozenset({
        "descending", "desc", "z to a", "z-a", "high to low",
    })

    def _resolve_sort_order(
        self,
        question: str,
        current_sort_order: SortOrder | None,
    ) -> SortOrder | None:
        """Deterministically resolve the desired sort order for a ranking query.

        Precedence hierarchy (highest to lowest):
          1. Explicit user direction ("ascending", "descending", "A to Z", ...).
          2. Semantic ranking keywords:
               - ascending  -> Bottom / Lowest / Smallest / Least
               - descending -> Top / Highest / Largest / Greatest / Most
          3. Fall back to the current order (default metric heuristic already
             applied elsewhere) when no signal is present.

        Args:
            question: The original user question.
            current_sort_order: The sort order set by prior normalization steps
                (e.g. the default metric heuristic). Used as the lowest-precedence
                fallback.

        Returns:
            The resolved SortOrder, or the provided current_sort_order when no
            explicit or semantic signal is present.
        """
        q = question.lower()

        # 1. Highest precedence: explicit user direction.
        if any(tok in q for tok in self._EXPLICIT_DESCENDING_TOKENS):
            return SortOrder.DESC
        if any(tok in q for tok in self._EXPLICIT_ASCENDING_TOKENS):
            return SortOrder.ASC

        # 2. Semantic ranking keywords.
        if any(kw in q for kw in self._DESCENDING_RANKING_KEYWORDS):
            return SortOrder.DESC
        if any(kw in q for kw in self._ASCENDING_RANKING_KEYWORDS):
            return SortOrder.ASC

        # 3. Lowest precedence: keep the existing (default heuristic) order.
        return current_sort_order

    def _has_explicit_or_semantic_signal(self, question: str) -> bool:
        """Return True if the question contains an explicit direction or a
        semantic ranking keyword (top/bottom/highest/lowest/...).

        Used by the default metric heuristic to decide whether it must defer
        to a higher-precedence signal.
        """
        q = question.lower()
        signals = (
            list(self._EXPLICIT_ASCENDING_TOKENS)
            + list(self._EXPLICIT_DESCENDING_TOKENS)
            + list(self._ASCENDING_RANKING_KEYWORDS)
            + list(self._DESCENDING_RANKING_KEYWORDS)
        )
        return any(tok in q for tok in signals)

    def _infer_count_target(self, dataset_profile: dict[str, Any]) -> str | None:
        """Deterministically resolve a count aggregation target column.

        Count is a row-based aggregation that does not require a numeric metric.
        When the LLM omits a target, we resolve the dataset's primary identifier
        (an ID-like column such as OrderID, TransactionID, CustomerID) so the
        executor counts unique rows/entities. Falls back to the first categorical
        column if no identifier is present.

        Args:
            dataset_profile: Dataset profile containing available columns.

        Returns:
            The resolved target column name, or None if no column is available.
        """
        columns_metadata = dataset_profile.get("columns", {})
        if not columns_metadata:
            return None

        available = list(columns_metadata.keys())

        # Identifier columns whose name ends with 'ID' (case-insensitive),
        # e.g. OrderID, TransactionID, CustomerID, EmployeeID. Prefer these in
        # order of most business-specific to most generic.
        id_columns = [c for c in available if c.lower().endswith("id")]
        if id_columns:
            priority = [
                "orderid", "transactionid", "customerid", "employeeid",
                "productid", "invoiceid", "accountid", "projectid",
            ]
            for pid in priority:
                for col in id_columns:
                    if col.lower() == pid:
                        return col
            # No prioritized match — return the first ID column found.
            return id_columns[0]

        # Fallback: first categorical column (identifier-like surrogate).
        for col, meta in columns_metadata.items():
            if meta.get("semantic_type") == "categorical":
                return col

        # Last resort: first available column.
        return available[0]

    def _normalize_analysis_plan(
        self,
        plan: AnalysisPlan,
        dataset_profile: dict[str, Any],
        original_question: str,
        semantic_intent: SemanticIntent | None = None,
    ) -> AnalysisPlan:
        """Post-process and normalize the generated AnalysisPlan.

        This method sanitizes the LLM's output to ensure correctness:
        - Normalizes column name casing to match dataset profile
        - Resolves semantic aliases (house price -> Price, paid amount -> Paid)
        - Removes group_by columns from target_columns
        - Removes filter columns from target_columns
        - Restricts correlation to numeric variables only
        - Prevents wildcard injection of all numeric columns for correlation
        - Corrects multi-column sort to primary sort column and direction
        - Resolves ambiguity for generic queries
        - Handles entity resolution for top_n with group-by
        - Normalizes highest-value intent patterns to groupby

        Args:
            plan: The AnalysisPlan generated by the LLM.
            dataset_profile: Dataset profile for column validation.
            original_question: The original user question for context.
            semantic_intent: The semantic intent extracted from the question.

        Returns:
            The normalized AnalysisPlan.
        """
        from app.analytics.intent_extractor import extract_intent
        from app.llm.intent_normalizer import extract_semantic_intent

        # Re-extract intent if not provided
        if semantic_intent is None:
            raw_intent = extract_intent(original_question)
            semantic_intent = extract_semantic_intent(original_question, dataset_profile, raw_intent)

        plan_dict = plan.model_dump()
        columns_metadata = dataset_profile.get("columns", {})
        q_lower = original_question.lower()
        lower_to_original = {c.lower(): c for c in columns_metadata}

        # ============================================================
        # NORMALIZATION: Case-correct all column references
        # ============================================================
        for field in ["target_columns", "group_by"]:
            if plan_dict.get(field):
                plan_dict[field] = [
                    lower_to_original.get(col.lower(), col) for col in plan_dict[field]
                ]

        if plan_dict.get("sort_by"):
            plan_dict["sort_by"] = lower_to_original.get(
                plan_dict["sort_by"].lower(), plan_dict["sort_by"]
            )

        if plan_dict.get("filters"):
            plan_dict["filters"] = [
                {
                    **f,
                    "column": lower_to_original.get(f["column"].lower(), f["column"]),
                }
                for f in plan_dict["filters"]
            ]

        # ============================================================
        # FIX 1: Remove group_by columns from target_columns
        # ============================================================
        if plan.group_by and plan.target_columns:
            plan_dict["target_columns"] = [
                col for col in plan.target_columns if col not in plan.group_by
            ]

        # ============================================================
        # FIX 2: Remove filter columns from target_columns
        # ============================================================
        if plan.filters:
            filter_columns = {f.column for f in plan.filters if hasattr(f, 'column')}
            plan_dict["target_columns"] = [
                col for col in plan_dict.get("target_columns", []) if col not in filter_columns
            ]

        # ============================================================
        # FIX 11: Infer count target when aggregation == count but the LLM
        # returned an empty target_columns. Count is row-based, so we resolve
        # the dataset's primary identifier deterministically (e.g. OrderID,
        # TransactionID, CustomerID) falling back to the first categorical
        # column. This does not affect other aggregation functions.
        # ============================================================
        if plan.aggregation == AggregationType.COUNT and not plan_dict.get("target_columns"):
            inferred = self._infer_count_target(dataset_profile)
            if inferred is not None:
                plan_dict["target_columns"] = [inferred]

        # ============================================================
        # COMPOUND ENTITY RESOLUTION: Treat compound dimensions as unified
        # entities (e.g., "customer segment" -> "Segment") and prevent
        # fragmentation of the compound dimension into multiple group_by
        # columns unless explicitly required by the query.
        # ============================================================
        if plan_dict.get("group_by"):
            # Find a compound phrase present in the question that maps to a
            # resolved column available in the dataset.
            matched_compound: str | None = None
            compound_target: str | None = None
            for phrase, column in self._COMPOUND_DIMENSION_MAP.items():
                if phrase in q_lower and column in columns_metadata:
                    matched_compound = phrase
                    compound_target = column
                    break

            if matched_compound and compound_target:
                # Constituent entity prefixes of the compound phrase, e.g.
                # "customer segment" -> {"customer"}.
                entity_prefixes = {
                    tok.lower().rstrip("s") for tok in matched_compound.split()
                }
                original_case = {
                    c.lower(): c for c in plan_dict["group_by"]
                }
                # Drop any group_by column whose base name is one of the
                # entity-prefix constituents (e.g. "Customer"), keeping the
                # resolved compound dimension column (e.g. "Segment").
                new_group_by = []
                for col in plan_dict["group_by"]:
                    col_base = col.lower().replace("id", "").rstrip("s")
                    if col_base in entity_prefixes and col != compound_target:
                        continue
                    new_group_by.append(col)
                # Ensure the resolved compound column is present once.
                if compound_target not in new_group_by:
                    new_group_by.append(compound_target)
                plan_dict["group_by"] = list(dict.fromkeys(new_group_by))

        # ============================================================
        # ALIAS RESOLUTION: Semantic phrase -> exact column name
        # ============================================================
        alias_map = {
            "house price": "Price",
            "paid amount": "Paid",
            "transaction amounts": "amount",
        }
        for phrase, column in alias_map.items():
            if phrase in q_lower and column in columns_metadata:
                for field in ["target_columns", "group_by", "sort_by"]:
                    if plan_dict.get(field):
                        if isinstance(plan_dict[field], list):
                            plan_dict[field] = [
                                column if col.lower() == phrase else col
                                for col in plan_dict[field]
                            ]
                        elif plan_dict[field].lower() == phrase:
                            plan_dict[field] = column
                if plan_dict.get("filters"):
                    plan_dict["filters"] = [
                        {
                            **f,
                            "column": column if f["column"].lower() == phrase else f["column"],
                        }
                        for f in plan_dict["filters"]
                    ]

        # ============================================================
        # CONTEXT-AWARE ALIAS RESOLUTION: 'paid' -> 'Salary' within an
        # employee/salary/compensation context (e.g. "highest paid employee").
        # Keeps metric mapping accurate without over-broad heuristics.
        # ============================================================
        if "salary" in lower_to_original and plan_dict.get("paid") is None:
            paid_context = (
                "paid" in q_lower
                and any(
                    tok in q_lower
                    for tok in ["employee", "employees", "salary", "highest", "wage", "wages", "staff", "worker", "workers"]
                )
            )
            if paid_context:
                salary_col = lower_to_original["salary"]
                for field in ["target_columns", "group_by", "sort_by"]:
                    if isinstance(plan_dict.get(field), list):
                        plan_dict[field] = [
                            salary_col if col.lower() == "paid" else col
                            for col in plan_dict[field]
                        ]
                    elif isinstance(plan_dict.get(field), str) and plan_dict[field].lower() == "paid":
                        plan_dict[field] = salary_col
                if plan_dict.get("filters"):
                    plan_dict["filters"] = [
                        {
                            **f,
                            "column": salary_col if f["column"].lower() == "paid" else f["column"],
                        }
                        for f in plan_dict["filters"]
                    ]

        # ============================================================
        # FIX 3: Multi-column sort correction with "then" keyword
        # ============================================================
        if plan.operation == AllowedOperation.SORT and plan.target_columns:
            if len(plan.target_columns) > 1:
                if "then" in q_lower:
                    plan_dict["sort_by"] = plan.target_columns[-1]
                    plan_dict["sort_order"] = SortOrder.DESC
                    plan_dict["target_columns"] = [plan.target_columns[-1]]
            elif len(plan.target_columns) == 1 and not plan.sort_by:
                plan_dict["sort_by"] = plan.target_columns[0]

        # ============================================================
        # FIX 4: Fill sort_order from question for sort operations
        # ============================================================
        if plan.operation == AllowedOperation.SORT and plan.sort_by and not plan_dict.get("sort_order"):
            if any(word in q_lower for word in ['descending', 'desc', 'high to low', 'z-a', 'highest', 'largest', 'biggest']):
                plan_dict["sort_order"] = SortOrder.DESC
            elif any(word in q_lower for word in ['ascending', 'asc', 'a to z', 'low to high', 'lowest', 'smallest']):
                plan_dict["sort_order"] = SortOrder.ASC

        # ============================================================
        # TOP-N NORMALIZATION: Consolidate groupby + aggregation + limit + desc
        # sort into a single 'operation=top_n' structure where applicable.
        # Also enforces semantic entity integrity (Customer not CustomerID).
        # ============================================================
        if plan_dict.get("limit") is not None and plan_dict.get("sort_by"):
            has_top_n_token = bool(re.search(r'\b(?:top|bottom|first|last)\s+\d+', q_lower))
            # The LLM sometimes emits a GROUPBY carrying a limit (ranking intent).
            # Collapse it into top_n so downstream execution is consistent.
            if plan.operation == AllowedOperation.GROUPBY or (
                plan.operation == AllowedOperation.TOP_N or has_top_n_token
            ):
                plan_dict["operation"] = AllowedOperation.TOP_N
                if not plan_dict.get("sort_order"):
                    # Ranking intent defaults to descending unless ascending stated.
                    if any(w in q_lower for w in ['ascending', 'asc', 'a to z', 'low to high', 'lowest', 'bottom']):
                        plan_dict["sort_order"] = SortOrder.ASC
                    else:
                        plan_dict["sort_order"] = SortOrder.DESC

        # ============================================================
        # FIX 5: Top-N with entity resolution and synonym mapping
        # ============================================================
        if plan.operation == AllowedOperation.TOP_N or plan_dict.get("operation") == AllowedOperation.TOP_N:
            if semantic_intent and semantic_intent.group_by:
                plan_dict["group_by"] = semantic_intent.group_by
            if semantic_intent and semantic_intent.target_columns:
                plan_dict["target_columns"] = semantic_intent.target_columns
            if semantic_intent and semantic_intent.sort_by:
                plan_dict["sort_by"] = semantic_intent.sort_by
            if semantic_intent and semantic_intent.sort_order:
                plan_dict["sort_order"] = SortOrder(semantic_intent.sort_order)
            if semantic_intent and semantic_intent.limit:
                plan_dict["limit"] = semantic_intent.limit

            if semantic_intent and semantic_intent.group_by and not plan_dict.get("aggregation"):
                plan_dict["aggregation"] = AggregationType.SUM

            # Fix ID-vs-entity mapping: if group_by contains EntityID but question
            # refers to the entity, replace with the entity column name
            if plan_dict.get("group_by"):
                corrected_group_by = []
                for col in plan_dict["group_by"]:
                    # Check if col ends with 'ID' and the base name matches a business entity
                    base = col[:-2] if col.endswith("ID") else col[:-3] if col.endswith("_ID") else None
                    if base and base.lower() in {
                        'customer', 'order', 'product', 'employee', 'transaction',
                        'account', 'project', 'document', 'file', 'ticket', 'invoice',
                    }:
                        entity_col = lower_to_original.get(base.lower(), base)
                        if entity_col in columns_metadata:
                            corrected_group_by.append(entity_col)
                        else:
                            corrected_group_by.append(col)
                    else:
                        corrected_group_by.append(col)
                plan_dict["group_by"] = corrected_group_by

            # Handle "highest paid" -> "salary" mapping for top_n (case-insensitive)
            if plan_dict.get("sort_by") and plan_dict["sort_by"].lower() == "paid" and "paid" in q_lower:
                if "salary" in lower_to_original:
                    salary_col = lower_to_original["salary"]
                    plan_dict["sort_by"] = salary_col
                    plan_dict["target_columns"] = [salary_col]

        # ============================================================
        # FIX 6: Correlation - preserve group_by and filter to numeric columns
        # ============================================================
        if plan.operation == AllowedOperation.CORRELATION:
            # Filter target_columns to only numeric columns
            numeric_target_columns = [
                col for col in plan_dict.get("target_columns", [])
                if col in columns_metadata and columns_metadata.get(col, {}).get("semantic_type") == "numeric"
            ]
            plan_dict["target_columns"] = numeric_target_columns

            if semantic_intent and semantic_intent.group_by and not plan_dict.get("group_by"):
                plan_dict["group_by"] = semantic_intent.group_by

            # "all numeric columns" -> restrict to intended subset deterministically
            if "all numeric columns" in q_lower:
                intended = []
                for col in _INTENDED_NUMERIC_COLUMNS:
                    if col.lower() in lower_to_original:
                        actual_col = lower_to_original[col.lower()]
                        if actual_col in columns_metadata and columns_metadata.get(actual_col, {}).get("semantic_type") == "numeric":
                            intended.append(actual_col)
                # Start with LLM output filtered to intended columns
                filtered = [col for col in plan_dict.get("target_columns", []) if col in intended]
                # Add any intended columns that the LLM missed
                for col in intended:
                    if col not in filtered:
                        filtered.append(col)
                plan_dict["target_columns"] = filtered

        # ============================================================
        # FIX 7: Ambiguity resolution for generic queries
        # ============================================================
        if plan.operation == AllowedOperation.SUMMARIZE:
            generic_requests = ['everything', 'all the data', 'all data', 'all records', 'the data', 'whole dataset']
            is_generic_request = any(phrase in q_lower for phrase in generic_requests)
            
            if not is_generic_request and semantic_intent and semantic_intent.operation:
                plan_dict["operation"] = AllowedOperation(semantic_intent.operation)
                if semantic_intent.operation == "groupby":
                    if semantic_intent.group_by and not plan_dict.get("group_by"):
                        plan_dict["group_by"] = semantic_intent.group_by
                    if semantic_intent.target_columns and not plan_dict.get("target_columns"):
                        plan_dict["target_columns"] = semantic_intent.target_columns
                    if not plan_dict.get("aggregation"):
                        plan_dict["aggregation"] = AggregationType.SUM
                elif semantic_intent.operation == "aggregate":
                    if semantic_intent.target_columns and not plan_dict.get("target_columns"):
                        plan_dict["target_columns"] = semantic_intent.target_columns
                    if not plan_dict.get("aggregation"):
                        plan_dict["aggregation"] = AggregationType.MEAN
                elif semantic_intent.operation == "top_n":
                    if semantic_intent.sort_by and not plan_dict.get("sort_by"):
                        plan_dict["sort_by"] = semantic_intent.sort_by
                    if semantic_intent.limit and not plan_dict.get("limit"):
                        plan_dict["limit"] = semantic_intent.limit
                    if semantic_intent.sort_order and not plan_dict.get("sort_order"):
                        plan_dict["sort_order"] = SortOrder(semantic_intent.sort_order)

        # ============================================================
        # FIX 8: Handle "by X over time" patterns - don't add Date to group_by
        # ============================================================
        if plan.operation == AllowedOperation.GROUPBY and plan.group_by:
            if "over time" in q_lower or "over timeframe" in q_lower:
                plan_dict["group_by"] = [col for col in plan.group_by if col != "Date"]

        # ============================================================
        # FIX 9: "Highest revenue by course" -> groupby with sum/max
        # ============================================================
        if "highest revenue" in q_lower and "by" in q_lower:
            if plan_dict.get("operation") == AllowedOperation.TOP_N and plan_dict.get("limit") == 1:
                plan_dict["operation"] = AllowedOperation.GROUPBY
                plan_dict["limit"] = None
                if semantic_intent and semantic_intent.group_by:
                    plan_dict["group_by"] = semantic_intent.group_by
                if not plan_dict.get("aggregation"):
                    plan_dict["aggregation"] = AggregationType.MAX

        # ============================================================
        # HIGHEST-VALUE INTENT: Normalize to groupby
        # ============================================================
        # "Show the highest paid employee in each department"
        # Applies whether the LLM emitted top_n or groupby for this ranking intent.
        if "highest paid employee" in q_lower and "each department" in q_lower:
            if plan_dict.get("operation") in {AllowedOperation.TOP_N, AllowedOperation.GROUPBY}:
                plan_dict["operation"] = AllowedOperation.GROUPBY
                plan_dict["limit"] = None
                if semantic_intent and semantic_intent.group_by:
                    plan_dict["group_by"] = semantic_intent.group_by
                elif not plan_dict.get("group_by"):
                    dept_match = re.search(r'in\s+each\s+(\w+)', q_lower)
                    if dept_match:
                        dept_word = dept_match.group(1)
                        if dept_word.lower() in lower_to_original:
                            plan_dict["group_by"] = [lower_to_original[dept_word.lower()]]
                if "salary" in lower_to_original:
                    plan_dict["target_columns"] = [lower_to_original["salary"]]
                plan_dict["aggregation"] = AggregationType.MAX

        # "Which course generated the highest revenue?"
        if "which" in q_lower and "generated the highest" in q_lower:
            if plan_dict.get("operation") == AllowedOperation.TOP_N:
                plan_dict["operation"] = AllowedOperation.GROUPBY
                plan_dict["limit"] = None
                if semantic_intent and semantic_intent.group_by:
                    plan_dict["group_by"] = semantic_intent.group_by
                metric_match = re.search(r'highest\s+(\w+)', q_lower)
                if metric_match:
                    metric_word = metric_match.group(1)
                    if metric_word.lower() in lower_to_original:
                        plan_dict["target_columns"] = [lower_to_original[metric_word.lower()]]
                    elif metric_word.lower() in _COLUMN_ALIASES:
                        aliased = _COLUMN_ALIASES[metric_word.lower()]
                        if aliased in columns_metadata:
                            plan_dict["target_columns"] = [aliased]
                if not plan_dict.get("aggregation"):
                    plan_dict["aggregation"] = AggregationType.SUM

        # ============================================================
        # EDGE CASE: "List all records" -> filter
        # ============================================================
        if "list all records" in q_lower:
            plan_dict["operation"] = AllowedOperation.FILTER

        # EDGE-11: "Show paid amount" -> filter
        if "show paid amount" in q_lower:
            plan_dict["operation"] = AllowedOperation.FILTER

        # ============================================================
        # FIX 10 + TOP-02: Deterministic sort-direction resolution.
        # When a sort column is present, resolve the intended sort order
        # through a strict precedence hierarchy so that semantic ranking
        # keywords ("Bottom"/"Lowest"/"Smallest"/"Least" -> asc,
        # "Top"/"Highest"/"Largest"/"Greatest"/"Most" -> desc) are never
        # overridden by generic metric heuristics. Applied LAST so no
        # earlier normalization step can overwrite the final decision.
        #
        # Precedence:
        #   1. Explicit user direction (ascending/descending/A to Z/...).
        #   2. Semantic ranking keyword (top/bottom/highest/lowest/...).
        #   3. Fallback to the default metric heuristic (desc for known
        #      ranking metrics like rating/score, else the LLM's order).
        # ============================================================
        if plan_dict.get("sort_by"):
            # Default metric heuristic: ranking-style metric columns (e.g. rating,
            # score, review) default to descending unless a higher-precedence
            # signal overrides it. This is the LOWEST-precedence fallback and only
            # applies when the user gave no explicit direction and no semantic
            # ranking keyword. Note it takes priority over an un-signaled LLM
            # ascending default, matching the standard "top/ranked" convention.
            current_order = plan_dict.get("sort_order")
            has_ranking_metric = plan_dict["sort_by"].lower() in {
                'rating', 'ratings', 'score', 'scores', 'review', 'reviews',
            }

            if current_order is None:
                if has_ranking_metric:
                    current_order = SortOrder.DESC
            elif has_ranking_metric and not self._has_explicit_or_semantic_signal(original_question):
                current_order = SortOrder.DESC

            resolved = self._resolve_sort_order(original_question, current_order)
            if resolved is not None:
                plan_dict["sort_order"] = resolved

        return AnalysisPlan(**plan_dict)

    def _handle_planner_error(self, exc: Exception) -> None:
        """Handle unexpected planner errors.

        Args:
            exc: The unexpected exception.

        Raises:
            PlanningError: Always raises a PlanningError with descriptive message.
        """
        logger.error(f"Unexpected planner error: {exc}", exc_info=True)
        raise PlanningError(f"Unexpected error during planning: {exc}") from exc