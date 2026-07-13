"""Pydantic schemas for user input and LLM-generated analysis plans."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AllowedOperation(str, Enum):
    """Approved analytics operations the executor may run."""

    SUMMARIZE = "summarize"
    FILTER = "filter"
    AGGREGATE = "aggregate"
    GROUPBY = "groupby"
    SORT = "sort"
    TOP_N = "top_n"
    CORRELATION = "correlation"


class AggregationType(str, Enum):
    """Approved aggregation functions for numeric columns."""

    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    STD = "std"


class SortOrder(str, Enum):
    """Approved sort directions."""

    ASC = "asc"
    DESC = "desc"


class ChartType(str, Enum):
    """Approved Plotly chart types returned to the frontend."""

    NONE = "none"
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"


class FilterOperator(str, Enum):
    """Approved filter operators for deterministic row selection."""

    EQ = "="
    NE = "!="
    GT = ">"
    LT = "<"
    GE = ">="
    LE = "<="
    CONTAINS = "contains"


def _validate_unique_columns(columns: list[str], *, field_name: str) -> list[str]:
    """Reject duplicate column names while preserving order."""
    normalized = [column.strip() for column in columns]
    if any(not column for column in normalized):
        raise ValueError(f"{field_name} must not contain empty column names.")

    seen: set[str] = set()
    duplicates: set[str] = set()
    for column in normalized:
        if column in seen:
            duplicates.add(column)
        seen.add(column)

    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"{field_name} must not contain duplicates: {duplicate_list}")

    return normalized


class UserQuery(BaseModel):
    """Incoming conversational query from the client."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(..., min_length=1, description="Active analytics session identifier.")
    question: str = Field(..., min_length=1, description="Natural-language question about the dataset.")

    @field_validator("question")
    @classmethod
    def validate_question_not_empty(cls, value: str) -> str:
        """Ensure the question contains non-whitespace content."""
        if not value.strip():
            raise ValueError("question must not be empty.")
        return value.strip()


class FilterCondition(BaseModel):
    """Single deterministic filter applied before analytics execution."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    column: str = Field(..., min_length=1, description="Dataset column to filter on.")
    operator: FilterOperator = Field(..., description="Comparison operator for the filter.")
    value: str | int | float | bool | None = Field(
        ...,
        description="Literal value used by the filter operator.",
    )

    @field_validator("column")
    @classmethod
    def validate_column_not_empty(cls, value: str) -> str:
        """Ensure the filter targets a named column."""
        if not value.strip():
            raise ValueError("column must not be empty.")
        return value.strip()


class AnalysisPlan(BaseModel):
    """Structured analysis plan produced by the LLM and executed by the backend."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: AllowedOperation = Field(..., description="Primary analytics operation to execute.")
    target_columns: list[str] = Field(
        default_factory=list,
        description="Columns directly involved in the requested analysis.",
    )
    group_by: list[str] = Field(
        default_factory=list,
        description="Columns used for grouped aggregations or breakdowns.",
    )
    filters: list[FilterCondition] = Field(
        default_factory=list,
        description="Deterministic pre-processing filters applied before execution.",
    )
    aggregation: AggregationType | None = Field(
        default=None,
        description="Aggregation function used when operation requires aggregation.",
    )
    sort_by: str | None = Field(
        default=None,
        description="Column used for sorting operation output.",
    )
    sort_order: SortOrder | None = Field(
        default=None,
        description="Sort direction for sort and top_n operations.",
    )
    limit: int | None = Field(
        default=None,
        gt=0,
        description="Maximum number of rows to return for sort or top_n operations.",
    )
    chart_type: ChartType = Field(
        default=ChartType.NONE,
        description="Requested visualization type for the analysis result.",
    )
    explanation_required: bool = Field(
        default=True,
        description="Whether the LLM should explain verified results to the user.",
    )

    @field_validator("target_columns")
    @classmethod
    def validate_target_columns(cls, value: list[str]) -> list[str]:
        """Ensure target column names are unique."""
        return _validate_unique_columns(value, field_name="target_columns")

    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, value: list[str]) -> list[str]:
        """Ensure group-by column names are unique."""
        return _validate_unique_columns(value, field_name="group_by")

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, value: str | None) -> str | None:
        """Normalize optional sort column names."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("sort_by must not be empty when provided.")
        return stripped
