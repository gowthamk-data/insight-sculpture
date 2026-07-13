"""Chart builder for converting ExecutionResult objects into Plotly visualizations.

This module is responsible for converting verified ExecutionResult objects into
publication-quality Plotly figures. It does NOT perform analytics, execute Pandas
operations, perform calculations, access uploaded datasets, or communicate with the LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pandas.api import types as ptypes

logger = logging.getLogger(__name__)


class ChartBuilderError(Exception):
    """Base exception for chart builder errors."""

    pass


class InvalidExecutionResultError(ChartBuilderError):
    """Raised when the execution result is invalid."""

    pass


class UnsupportedChartTypeError(ChartBuilderError):
    """Raised when the requested chart type is not supported."""

    pass


class EmptyDatasetError(ChartBuilderError):
    """Raised when the dataset is empty."""

    pass


class MissingColumnError(ChartBuilderError):
    """Raised when required columns are missing."""

    pass


@dataclass
class ChartResult:
    """Structured result from the chart builder.

    Contains the Plotly figure along with metadata for downstream consumption.
    """

    figure: go.Figure
    """The Plotly figure object."""

    chart_type: str
    """The type of chart that was created."""

    title: str
    """The chart title."""

    description: str
    """A brief description of what the chart shows."""

    x_axis: str | None
    """The x-axis label."""

    y_axis: str | None
    """The y-axis label."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the chart."""


class ChartBuilder:
    """Converts ExecutionResult objects into Plotly visualizations.

    The chart builder uses the execution result's chart recommendation to determine
    the appropriate visualization type. It validates the data before creating charts
    and produces publication-quality figures with proper labels, legends, and tooltips.
    """

    # Supported chart types
    SUPPORTED_CHARTS = {
        "bar",
        "line",
        "scatter",
        "pie",
        "histogram",
        "box",
        "heatmap",
    }

    def __init__(self) -> None:
        """Initialize the chart builder."""
        self._chart_builders = {
            "bar": self._build_bar_chart,
            "line": self._build_line_chart,
            "scatter": self._build_scatter_chart,
            "pie": self._build_pie_chart,
            "histogram": self._build_histogram,
            "box": self._build_box_chart,
            "heatmap": self._build_heatmap,
        }

    def build_chart(self, execution_result: Any) -> ChartResult:
        """Convert an ExecutionResult into a Plotly visualization.

        Args:
            execution_result: ExecutionResult from the analytics executor.

        Returns:
            A ChartResult containing the Plotly figure and metadata.

        Raises:
            InvalidExecutionResultError: If the execution result is invalid.
            UnsupportedChartTypeError: If the chart type is not supported.
            EmptyDatasetError: If the dataset is empty.
            MissingColumnError: If required columns are missing.
        """
        # Validate execution result
        self._validate_execution_result(execution_result)

        # Get chart recommendation
        chart_type = execution_result.chart_recommendation

        # Handle "none" recommendation
        if chart_type == "none" or not chart_type:
            raise UnsupportedChartTypeError(
                "No chart recommended for this analysis result."
            )

        # Validate chart type is supported
        if chart_type not in self.SUPPORTED_CHARTS:
            raise UnsupportedChartTypeError(
                f"Unsupported chart type: {chart_type}. "
                f"Supported types: {', '.join(sorted(self.SUPPORTED_CHARTS))}"
            )

        # Get the dataframe
        df = execution_result.dataframe

        # Validate dataframe is not empty
        if df.empty:
            raise EmptyDatasetError("Cannot create chart from empty dataset.")

        # Select the appropriate chart builder
        chart_builder = self._chart_builders.get(chart_type)
        if chart_builder is None:
            raise UnsupportedChartTypeError(f"No builder available for chart type: {chart_type}")

        # Build the chart
        return chart_builder(df, execution_result)

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
        required_attrs = ["dataframe", "chart_recommendation", "metadata"]
        for attr in required_attrs:
            if not hasattr(execution_result, attr):
                raise InvalidExecutionResultError(
                    f"Execution result missing required attribute: {attr}"
                )

        # Validate dataframe is a DataFrame
        if not isinstance(execution_result.dataframe, pd.DataFrame):
            raise InvalidExecutionResultError(
                "Execution result dataframe must be a pandas DataFrame."
            )

    def _build_bar_chart(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a bar chart from the execution result.

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a bar chart.
        """
        # Determine x and y columns
        columns = df.columns.tolist()
        metadata = execution_result.metadata

        # Use group_by columns for x-axis if available
        x_col = metadata.get("group_by", [columns[0]])[0] if metadata.get("group_by") else columns[0]
        
        # Use target columns for y-axis if available
        y_cols = metadata.get("columns_used", columns[1:])
        y_col = y_cols[0] if y_cols else columns[1] if len(columns) > 1 else columns[0]

        # Validate columns exist
        self._validate_columns_exist(df, [x_col, y_col])

        # Create bar chart
        fig = px.bar(
            df,
            x=x_col,
            y=y_col,
            title=f"{y_col} by {x_col}",
            labels={x_col: x_col, y_col: y_col},
        )

        # Update layout
        fig.update_layout(
            xaxis_title=x_col,
            yaxis_title=y_col,
            hovermode="x unified",
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="bar",
            title=f"{y_col} by {x_col}",
            description=f"Bar chart showing {y_col} grouped by {x_col}.",
            x_axis=x_col,
            y_axis=y_col,
            metadata=self._build_metadata(execution_result, "bar"),
        )

    def _build_line_chart(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a line chart from the execution result.

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a line chart.
        """
        # Determine x and y columns
        columns = df.columns.tolist()
        
        # Look for datetime column for x-axis
        datetime_cols = [
            col for col in columns
            if ptypes.is_datetime64_any_dtype(df[col])
        ]
        x_col = datetime_cols[0] if datetime_cols else columns[0]
        
        # Use first numeric column for y-axis
        numeric_cols = [
            col for col in columns
            if ptypes.is_numeric_dtype(df[col]) and col != x_col
        ]
        y_col = numeric_cols[0] if numeric_cols else columns[1] if len(columns) > 1 else columns[0]

        # Validate columns exist
        self._validate_columns_exist(df, [x_col, y_col])

        # Create line chart
        fig = px.line(
            df,
            x=x_col,
            y=y_col,
            title=f"{y_col} over {x_col}",
            labels={x_col: x_col, y_col: y_col},
        )

        # Update layout
        fig.update_layout(
            xaxis_title=x_col,
            yaxis_title=y_col,
            hovermode="x unified",
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="line",
            title=f"{y_col} over {x_col}",
            description=f"Line chart showing {y_col} over {x_col}.",
            x_axis=x_col,
            y_axis=y_col,
            metadata=self._build_metadata(execution_result, "line"),
        )

    def _build_scatter_chart(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a scatter plot from the execution result.

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a scatter plot.
        """
        # Determine x and y columns
        columns = df.columns.tolist()
        numeric_cols = [
            col for col in columns
            if ptypes.is_numeric_dtype(df[col])
        ]

        if len(numeric_cols) < 2:
            raise MissingColumnError(
                "Scatter plot requires at least two numeric columns."
            )

        x_col = numeric_cols[0]
        y_col = numeric_cols[1]

        # Validate columns exist
        self._validate_columns_exist(df, [x_col, y_col])

        # Create scatter plot
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            title=f"{y_col} vs {x_col}",
            labels={x_col: x_col, y_col: y_col},
        )

        # Update layout
        fig.update_layout(
            xaxis_title=x_col,
            yaxis_title=y_col,
            hovermode="closest",
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="scatter",
            title=f"{y_col} vs {x_col}",
            description=f"Scatter plot showing relationship between {x_col} and {y_col}.",
            x_axis=x_col,
            y_axis=y_col,
            metadata=self._build_metadata(execution_result, "scatter"),
        )

    def _build_pie_chart(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a pie chart from the execution result.

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a pie chart.
        """
        # Determine columns
        columns = df.columns.tolist()
        
        # Use first column as labels, second as values
        label_col = columns[0]
        value_col = columns[1] if len(columns) > 1 else columns[0]

        # Validate columns exist
        self._validate_columns_exist(df, [label_col, value_col])

        # Create pie chart
        fig = px.pie(
            df,
            values=value_col,
            names=label_col,
            title=f"Distribution of {label_col}",
        )

        # Update layout
        fig.update_layout(
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="pie",
            title=f"Distribution of {label_col}",
            description=f"Pie chart showing distribution of {label_col}.",
            x_axis=None,
            y_axis=None,
            metadata=self._build_metadata(execution_result, "pie"),
        )

    def _build_histogram(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a histogram from the execution result.

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a histogram.
        """
        # Determine numeric column
        columns = df.columns.tolist()
        numeric_cols = [
            col for col in columns
            if ptypes.is_numeric_dtype(df[col])
        ]

        if not numeric_cols:
            raise MissingColumnError(
                "Histogram requires at least one numeric column."
            )

        x_col = numeric_cols[0]

        # Validate column exists
        self._validate_columns_exist(df, [x_col])

        # Create histogram
        fig = px.histogram(
            df,
            x=x_col,
            title=f"Distribution of {x_col}",
            labels={x_col: x_col},
        )

        # Update layout
        fig.update_layout(
            xaxis_title=x_col,
            yaxis_title="Count",
            hovermode="x unified",
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="histogram",
            title=f"Distribution of {x_col}",
            description=f"Histogram showing distribution of {x_col}.",
            x_axis=x_col,
            y_axis="Count",
            metadata=self._build_metadata(execution_result, "histogram"),
        )

    def _build_box_chart(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a box plot from the execution result.

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a box plot.
        """
        # Determine numeric column
        columns = df.columns.tolist()
        numeric_cols = [
            col for col in columns
            if ptypes.is_numeric_dtype(df[col])
        ]

        if not numeric_cols:
            raise MissingColumnError(
                "Box plot requires at least one numeric column."
            )

        y_col = numeric_cols[0]

        # Look for categorical column for grouping
        categorical_cols = [
            col for col in columns
            if not ptypes.is_numeric_dtype(df[col]) and col != y_col
        ]
        x_col = categorical_cols[0] if categorical_cols else None

        # Validate columns exist
        cols_to_validate = [y_col]
        if x_col:
            cols_to_validate.append(x_col)
        self._validate_columns_exist(df, cols_to_validate)

        # Create box plot
        if x_col:
            fig = px.box(
                df,
                x=x_col,
                y=y_col,
                title=f"Distribution of {y_col} by {x_col}",
                labels={x_col: x_col, y_col: y_col},
            )
        else:
            fig = px.box(
                df,
                y=y_col,
                title=f"Distribution of {y_col}",
                labels={y_col: y_col},
            )

        # Update layout
        fig.update_layout(
            xaxis_title=x_col if x_col else None,
            yaxis_title=y_col,
            hovermode="x unified",
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="box",
            title=f"Distribution of {y_col} by {x_col}" if x_col else f"Distribution of {y_col}",
            description=f"Box plot showing distribution of {y_col}.",
            x_axis=x_col,
            y_axis=y_col,
            metadata=self._build_metadata(execution_result, "box"),
        )

    def _build_heatmap(self, df: pd.DataFrame, execution_result: Any) -> ChartResult:
        """Build a heatmap from the execution result (typically for correlation matrices).

        Args:
            df: The dataframe to visualize.
            execution_result: The execution result for metadata.

        Returns:
            A ChartResult with a heatmap.
        """
        # For correlation matrices, the first column is typically the index
        columns = df.columns.tolist()
        
        # If first column is "column" or similar, it's the index
        if columns[0].lower() in ["column", "index", ""]:
            value_cols = columns[1:]
            df_values = df.set_index(columns[0])
        else:
            value_cols = columns
            df_values = df

        # Validate columns exist
        self._validate_columns_exist(df, value_cols)

        # Create heatmap
        fig = px.imshow(
            df_values,
            title="Correlation Heatmap",
            labels=dict(x="Variable", y="Variable", color="Correlation"),
            color_continuous_scale="RdBu",
            aspect="auto",
        )

        # Update layout
        fig.update_layout(
            xaxis_title="Variable",
            yaxis_title="Variable",
            responsive=True,
        )

        return ChartResult(
            figure=fig,
            chart_type="heatmap",
            title="Correlation Heatmap",
            description="Heatmap showing correlation between variables.",
            x_axis="Variable",
            y_axis="Variable",
            metadata=self._build_metadata(execution_result, "heatmap"),
        )

    def _validate_columns_exist(self, df: pd.DataFrame, columns: list[str]) -> None:
        """Validate that all specified columns exist in the dataframe.

        Args:
            df: The dataframe to check.
            columns: List of column names to validate.

        Raises:
            MissingColumnError: If any column does not exist.
        """
        missing = [col for col in columns if col not in df.columns]
        if missing:
            missing_str = ", ".join(missing)
            raise MissingColumnError(f"Columns not found in dataset: {missing_str}")

    def _build_metadata(self, execution_result: Any, chart_type: str) -> dict[str, Any]:
        """Build metadata for the chart result.

        Args:
            execution_result: The execution result.
            chart_type: The type of chart created.

        Returns:
            Metadata dictionary.
        """
        return {
            "chart_type": chart_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rows_returned": execution_result.rows_returned,
            "columns_returned": execution_result.columns_returned,
            "operation": execution_result.metadata.get("operation", "unknown"),
        }
