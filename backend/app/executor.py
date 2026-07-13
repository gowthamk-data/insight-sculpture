"""Deterministic analytics executor for validated analysis plans."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.schemas import (
    AggregationType,
    AllowedOperation,
    AnalysisPlan,
    ChartType,
    FilterCondition,
    FilterOperator,
    SortOrder,
)
from app.session import DatasetSessionManager

SummaryDict = dict[str, Any]
MetadataDict = dict[str, Any]

NUMERIC_AGGREGATIONS: frozenset[AggregationType] = frozenset(
    {
        AggregationType.SUM,
        AggregationType.MEAN,
        AggregationType.MEDIAN,
        AggregationType.STD,
    }
)

AGGREGATION_FUNCTIONS: dict[AggregationType, str] = {
    AggregationType.SUM: "sum",
    AggregationType.MEAN: "mean",
    AggregationType.MEDIAN: "median",
    AggregationType.COUNT: "count",
    AggregationType.MIN: "min",
    AggregationType.MAX: "max",
    AggregationType.STD: "std",
}


@dataclass
class ExecutionResult:
    """Structured output from a deterministic analytics execution."""

    dataframe: pd.DataFrame
    summary: SummaryDict
    rows_returned: int
    columns_returned: int
    execution_time_ms: float
    chart_recommendation: str
    metadata: MetadataDict = field(default_factory=dict)


class DataExecutor:
    """Execute validated analysis plans using deterministic Pandas operations."""

    def __init__(self, session_manager: DatasetSessionManager) -> None:
        """Initialize the executor with a dataset session manager.

        Args:
            session_manager: In-memory store for uploaded dataset sessions.
        """
        self._session_manager = session_manager
        self._operation_handlers: dict[
            AllowedOperation, Callable[[pd.DataFrame, AnalysisPlan], tuple[pd.DataFrame, SummaryDict]]
        ] = {
            AllowedOperation.SUMMARIZE: self._execute_summary,
            AllowedOperation.FILTER: self._execute_filter,
            AllowedOperation.AGGREGATE: self._execute_aggregate,
            AllowedOperation.GROUPBY: self._execute_groupby,
            AllowedOperation.SORT: self._execute_sort,
            AllowedOperation.TOP_N: self._execute_top_n,
            AllowedOperation.CORRELATION: self._execute_correlation,
        }

    def execute(self, session_id: str, plan: AnalysisPlan) -> ExecutionResult:
        """Execute a validated analysis plan against a stored dataset.

        Args:
            session_id: Identifier for the uploaded dataset session.
            plan: Validated analysis plan produced by the LLM planner.

        Returns:
            Structured execution output for downstream explanation and charting.

        Raises:
            KeyError: If the session does not exist.
            ValueError: If validation fails or the operation is unsupported.
        """
        start_time = time.perf_counter()

        source_df = self._session_manager.get_dataframe(session_id)
        working_df = source_df.copy()
        columns_used = self._resolve_columns_used(plan)

        if columns_used:
            self._validate_columns_exist(working_df, columns_used)

        if plan.filters:
            self._validate_filter_columns(working_df, plan.filters)
            working_df = self._apply_filters(working_df, plan.filters)
            if working_df.empty:
                raise ValueError("Empty result after applying filters.")

        handler = self._operation_handlers.get(plan.operation)
        if handler is None:
            raise ValueError(f"Unsupported operation: {plan.operation.value}")

        result_df, summary = handler(working_df, plan)
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        metadata = self._build_metadata(plan, columns_used)
        chart_recommendation = self._recommend_chart(plan, result_df)

        return ExecutionResult(
            dataframe=result_df,
            summary=summary,
            rows_returned=int(result_df.shape[0]),
            columns_returned=int(result_df.shape[1]),
            execution_time_ms=execution_time_ms,
            chart_recommendation=chart_recommendation,
            metadata=metadata,
        )

    def _execute_summary(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Return dataset shape plus numeric and categorical summaries."""
        columns = plan.target_columns or list(df.columns)
        self._validate_columns_exist(df, columns)

        selected_df = df[columns]
        numeric_columns = [column for column in columns if self._is_numeric_column(df[column])]
        categorical_columns = [
            column for column in columns if column not in numeric_columns
        ]

        numeric_summary = self._build_numeric_summary(df, numeric_columns)
        categorical_summary = self._build_categorical_summary(df, categorical_columns)

        summary: SummaryDict = {
            "row_count": int(df.shape[0]),
            "column_count": int(df.shape[1]),
            "numeric_summary": numeric_summary,
            "categorical_summary": categorical_summary,
        }
        return selected_df, summary

    def _execute_filter(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Return the filtered dataset. Filters are already applied upstream."""
        filtered_df = df
        summary: SummaryDict = {
            "rows_matched": int(filtered_df.shape[0]),
            "filters_applied": len(plan.filters),
        }
        return filtered_df, summary

    def _execute_aggregate(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Aggregate target columns using a single approved aggregation."""
        if not plan.target_columns:
            raise ValueError("aggregate operation requires at least one target column.")
        if plan.aggregation is None:
            raise ValueError("aggregate operation requires an aggregation.")

        self._validate_columns_exist(df, plan.target_columns)
        self._validate_aggregation(plan.aggregation, plan.target_columns, df)

        agg_name = AGGREGATION_FUNCTIONS[plan.aggregation]
        aggregated = df[plan.target_columns].agg(agg_name)
        result_df = aggregated.to_frame().T
        result_df.index = ["aggregate"]

        summary: SummaryDict = {
            "aggregation": plan.aggregation.value,
            "target_columns": plan.target_columns,
        }
        return result_df, summary

    def _execute_groupby(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Group by one or more columns and aggregate target columns."""
        if not plan.group_by:
            raise ValueError("groupby operation requires at least one group_by column.")
        if not plan.target_columns:
            raise ValueError("groupby operation requires at least one target column.")
        if plan.aggregation is None:
            raise ValueError("groupby operation requires an aggregation.")

        self._validate_groupby_columns(df, plan.group_by)
        self._validate_columns_exist(df, plan.target_columns)
        self._validate_aggregation(plan.aggregation, plan.target_columns, df)

        agg_name = AGGREGATION_FUNCTIONS[plan.aggregation]
        grouped = df.groupby(plan.group_by, dropna=False)[plan.target_columns].agg(agg_name)
        result_df = grouped.reset_index()

        summary: SummaryDict = {
            "group_by": plan.group_by,
            "aggregation": plan.aggregation.value,
            "target_columns": plan.target_columns,
            "groups_returned": int(result_df.shape[0]),
        }
        return result_df, summary

    def _execute_sort(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Sort the dataset by one or more columns."""
        sort_columns = self._resolve_sort_columns(plan)
        self._validate_sort_columns(df, sort_columns)

        ascending = plan.sort_order != SortOrder.DESC
        sorted_df = df.sort_values(by=sort_columns, ascending=ascending, kind="mergesort")

        summary: SummaryDict = {
            "sort_by": sort_columns,
            "sort_order": (plan.sort_order or SortOrder.ASC).value,
            "rows_returned": int(sorted_df.shape[0]),
        }
        return sorted_df, summary

    def _execute_top_n(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Return the largest or smallest N rows based on a sort column."""
        if plan.sort_by is None:
            raise ValueError("top_n operation requires sort_by.")
        if plan.limit is None:
            raise ValueError("top_n operation requires a positive limit.")

        sort_columns = self._resolve_sort_columns(plan)
        self._validate_sort_columns(df, sort_columns)

        ascending = plan.sort_order != SortOrder.DESC
        sorted_df = df.sort_values(by=sort_columns, ascending=ascending, kind="mergesort")
        result_df = sorted_df.head(plan.limit)

        summary: SummaryDict = {
            "sort_by": sort_columns,
            "sort_order": (plan.sort_order or SortOrder.DESC).value,
            "limit": plan.limit,
            "rows_returned": int(result_df.shape[0]),
        }
        return result_df, summary

    def _execute_correlation(
        self, df: pd.DataFrame, plan: AnalysisPlan
    ) -> tuple[pd.DataFrame, SummaryDict]:
        """Return a correlation matrix for selected numeric columns."""
        if not plan.target_columns:
            raise ValueError("correlation operation requires at least one target column.")

        self._validate_columns_exist(df, plan.target_columns)
        self._validate_numeric_columns(df, plan.target_columns)

        numeric_df = df[plan.target_columns].apply(pd.to_numeric, errors="coerce")
        correlation_matrix = numeric_df.corr(numeric_only=True)
        result_df = correlation_matrix.reset_index().rename(columns={"index": "column"})

        summary: SummaryDict = {
            "target_columns": plan.target_columns,
            "matrix_size": int(correlation_matrix.shape[0]),
        }
        return result_df, summary

    def _apply_filters(self, df: pd.DataFrame, filters: list[FilterCondition]) -> pd.DataFrame:
        """Apply all filter conditions using vectorized AND logic."""
        if not filters:
            return df

        combined_mask = pd.Series(True, index=df.index)
        for condition in filters:
            combined_mask &= self._build_filter_mask(df[condition.column], condition)

        return df.loc[combined_mask]

    def _build_filter_mask(self, series: pd.Series, condition: FilterCondition) -> pd.Series:
        """Build a boolean mask for a single filter condition."""
        operator = condition.operator
        value = condition.value

        if operator == FilterOperator.EQ:
            return series.eq(value)
        if operator == FilterOperator.NE:
            return series.ne(value)
        if operator == FilterOperator.GT:
            return series.gt(value)
        if operator == FilterOperator.LT:
            return series.lt(value)
        if operator == FilterOperator.GE:
            return series.ge(value)
        if operator == FilterOperator.LE:
            return series.le(value)
        if operator == FilterOperator.CONTAINS:
            if value is None:
                raise ValueError("contains filter requires a non-null value.")
            return series.astype(str).str.contains(str(value), case=False, na=False)

        raise ValueError(f"Unsupported filter operator: {operator.value}")

    def _validate_columns_exist(self, df: pd.DataFrame, columns: list[str]) -> None:
        """Ensure all requested columns exist in the dataframe."""
        missing = [column for column in columns if column not in df.columns]
        if missing:
            missing_list = ", ".join(missing)
            raise ValueError(f"Unknown column(s): {missing_list}")

    def _validate_numeric_columns(self, df: pd.DataFrame, columns: list[str]) -> None:
        """Ensure all requested columns are numeric."""
        self._validate_columns_exist(df, columns)
        non_numeric = [column for column in columns if not self._is_numeric_column(df[column])]
        if non_numeric:
            column_list = ", ".join(non_numeric)
            raise ValueError(f"Non-numeric column(s): {column_list}")

    def _validate_groupby_columns(self, df: pd.DataFrame, columns: list[str]) -> None:
        """Ensure all group-by columns exist in the dataframe."""
        self._validate_columns_exist(df, columns)

    def _validate_sort_column(self, df: pd.DataFrame, column: str) -> None:
        """Ensure the sort column exists in the dataframe."""
        self._validate_columns_exist(df, [column])

    def _validate_sort_columns(self, df: pd.DataFrame, columns: list[str]) -> None:
        """Ensure all sort columns exist in the dataframe."""
        self._validate_columns_exist(df, columns)

    def _validate_filter_columns(
        self, df: pd.DataFrame, filters: list[FilterCondition]
    ) -> None:
        """Ensure all filter columns exist in the dataframe."""
        filter_columns = [condition.column for condition in filters]
        self._validate_columns_exist(df, filter_columns)

    def _validate_aggregation(
        self,
        aggregation: AggregationType,
        target_columns: list[str],
        df: pd.DataFrame,
    ) -> None:
        """Ensure the aggregation is valid for the selected target columns."""
        if aggregation not in AGGREGATION_FUNCTIONS:
            raise ValueError(f"Invalid aggregation: {aggregation.value}")

        if aggregation in NUMERIC_AGGREGATIONS:
            self._validate_numeric_columns(df, target_columns)

    def _resolve_columns_used(self, plan: AnalysisPlan) -> list[str]:
        """Collect all columns referenced by the analysis plan."""
        columns: list[str] = []
        columns.extend(plan.target_columns)
        columns.extend(plan.group_by)

        if plan.sort_by is not None:
            columns.append(plan.sort_by)

        columns.extend(condition.column for condition in plan.filters)

        seen: set[str] = set()
        unique_columns: list[str] = []
        for column in columns:
            if column not in seen:
                seen.add(column)
                unique_columns.append(column)
        return unique_columns

    def _resolve_sort_columns(self, plan: AnalysisPlan) -> list[str]:
        """Resolve the full list of sort columns for sort and top_n operations."""
        if plan.sort_by is None:
            raise ValueError("sort operation requires sort_by.")

        sort_columns = [plan.sort_by]
        for column in plan.target_columns:
            if column != plan.sort_by and column not in sort_columns:
                sort_columns.append(column)
        return sort_columns

    def _build_metadata(self, plan: AnalysisPlan, columns_used: list[str]) -> MetadataDict:
        """Build execution metadata for downstream consumers."""
        return {
            "operation": plan.operation.value,
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "columns_used": columns_used,
            "filters_applied": [
                {
                    "column": condition.column,
                    "operator": condition.operator.value,
                    "value": condition.value,
                }
                for condition in plan.filters
            ],
            "aggregation": plan.aggregation.value if plan.aggregation else None,
            "group_by": plan.group_by,
            "sort_by": plan.sort_by,
            "limit": plan.limit,
        }

    def _recommend_chart(self, plan: AnalysisPlan, result_df: pd.DataFrame) -> str:
        """Recommend an appropriate chart type without generating a chart."""
        if plan.operation == AllowedOperation.CORRELATION:
            return "heatmap"
        if plan.chart_type != ChartType.NONE:
            return plan.chart_type.value
        if plan.operation == AllowedOperation.GROUPBY:
            return "bar"
        if plan.operation == AllowedOperation.FILTER:
            return "bar" if result_df.shape[0] <= 25 else "none"

        numeric_columns = [
            column for column in result_df.columns if self._is_numeric_column(result_df[column])
        ]
        datetime_columns = [
            column
            for column in result_df.columns
            if ptypes.is_datetime64_any_dtype(result_df[column])
        ]
        categorical_columns = [
            column
            for column in result_df.columns
            if column not in numeric_columns and column not in datetime_columns
        ]

        if len(numeric_columns) >= 2 and plan.operation in {
            AllowedOperation.SORT,
            AllowedOperation.TOP_N,
            AllowedOperation.AGGREGATE,
        }:
            return "scatter"
        if datetime_columns and numeric_columns:
            return "line"
        if categorical_columns and len(result_df) <= 20:
            return "pie"
        if numeric_columns:
            return "histogram"

        return "none"

    def _build_numeric_summary(
        self, df: pd.DataFrame, numeric_columns: list[str]
    ) -> dict[str, dict[str, float | None]]:
        """Compute numeric summary statistics for the requested columns."""
        summary: dict[str, dict[str, float | None]] = {}
        for column in numeric_columns:
            series = pd.to_numeric(df[column], errors="coerce")
            summary[column] = {
                "min": self._safe_float(series.min()),
                "max": self._safe_float(series.max()),
                "mean": self._safe_float(series.mean()),
                "median": self._safe_float(series.median()),
                "std": self._safe_float(series.std()),
            }
        return summary

    def _build_categorical_summary(
        self, df: pd.DataFrame, categorical_columns: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Compute top categorical value counts for the requested columns."""
        summary: dict[str, list[dict[str, Any]]] = {}
        for column in categorical_columns:
            value_counts = df[column].value_counts(dropna=True).head(5)
            summary[column] = [
                {"value": self._json_safe_value(value), "count": int(count)}
                for value, count in value_counts.items()
            ]
        return summary

    @staticmethod
    def _is_numeric_column(series: pd.Series) -> bool:
        """Return True when a column should be treated as numeric."""
        return bool(ptypes.is_numeric_dtype(series))

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        """Convert a scalar to a JSON-safe float."""
        if value is None or pd.isna(value):
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(numeric_value):
            return None
        return numeric_value

    @staticmethod
    def _json_safe_value(value: Any) -> Any:
        """Convert a scalar value into a JSON-friendly representation."""
        if value is None or pd.isna(value):
            return None
        if isinstance(value, (np.integer, int)):
            return int(value)
        if isinstance(value, (np.floating, float)):
            return DataExecutor._safe_float(value)
        if isinstance(value, (np.bool_, bool)):
            return bool(value)
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        return str(value)
