"""Dataset profiling utilities for producing LLM-safe dataset metadata."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

SemanticType = str
ProfileDict = dict[str, Any]


class DatasetProfiler:
    """Build structured, JSON-serializable metadata for uploaded datasets."""

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".xlsx", ".xls"})
    SAMPLE_ROW_COUNT: int = 3
    CATEGORICAL_TOP_VALUE_COUNT: int = 5

    def profile_file(self, file_path: str) -> ProfileDict:
        """Load a supported dataset file and return its structured profile.

        Args:
            file_path: Absolute or relative path to a CSV or Excel workbook.

        Returns:
            A JSON-serializable dictionary describing dataset structure and
            lightweight column-level statistics.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the extension is unsupported or the dataset is empty.
            RuntimeError: If the file cannot be parsed as a dataset.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Dataset file not found: {file_path}")

        extension = path.suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(self.SUPPORTED_EXTENSIONS))
            raise ValueError(
                f"Unsupported file extension '{extension}'. Supported extensions: {supported}."
            )

        try:
            dataframe = self._load_dataset(path, extension)
        except Exception as exc:
            raise RuntimeError(f"Failed to load dataset '{file_path}': {exc}") from exc

        if dataframe.empty:
            raise ValueError("Dataset is empty and cannot be profiled.")

        return self.generate_profile(dataframe)

    def generate_profile(self, df: pd.DataFrame) -> ProfileDict:
        """Generate structured metadata for an in-memory dataset.

        Args:
            df: Loaded dataset to describe.

        Returns:
            A JSON-serializable profile dictionary containing shape, sample
            rows, and per-column metadata.

        Raises:
            ValueError: If the dataframe is empty.
        """
        if df.empty:
            raise ValueError("Dataset is empty and cannot be profiled.")

        row_count, column_count = df.shape
        columns_metadata: dict[str, ProfileDict] = {}

        for column_name in df.columns:
            series = df[column_name]
            columns_metadata[str(column_name)] = self._profile_column(series)

        profile: ProfileDict = {
            "shape": {
                "rows": int(row_count),
                "columns": int(column_count),
            },
            "sample_rows": self._json_safe_sample_rows(df.head(self.SAMPLE_ROW_COUNT)),
            "columns": columns_metadata,
        }

        # Validate JSON serializability before returning to callers.
        json.dumps(profile)
        return profile

    def _load_dataset(self, path: Path, extension: str) -> pd.DataFrame:
        """Load a dataset from disk using the appropriate Pandas reader."""
        if extension == ".csv":
            return pd.read_csv(path)

        if extension == ".xlsx":
            return pd.read_excel(path, engine="openpyxl")

        if extension == ".xls":
            return pd.read_excel(path)

        supported = ", ".join(sorted(self.SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file extension '{extension}'. Supported extensions: {supported}."
        )

    def _profile_column(self, series: pd.Series) -> ProfileDict:
        """Build metadata for a single column in one pass."""
        non_null_count = int(series.count())
        total_count = int(len(series))
        missing_values = total_count - non_null_count
        missing_percentage = self._safe_float(
            (missing_values / total_count) * 100 if total_count else 0.0
        )

        semantic_type = self._infer_semantic_type(series)
        column_profile: ProfileDict = {
            "inferred_type": str(series.dtype),
            "semantic_type": semantic_type,
            "missing_values": missing_values,
            "missing_percentage": missing_percentage,
            "unique_values_count": int(series.nunique(dropna=True)),
        }

        if semantic_type == "numeric":
            column_profile.update(self._numeric_summary(series))
        elif semantic_type == "datetime":
            column_profile.update(self._datetime_summary(series))
        elif semantic_type == "categorical":
            column_profile.update(self._categorical_samples(series))

        return column_profile

    def _infer_semantic_type(self, series: pd.Series) -> SemanticType:
        """Infer a high-level semantic type using pandas.api.types helpers."""
        if ptypes.is_bool_dtype(series):
            return "boolean"
        if ptypes.is_datetime64_any_dtype(series):
            return "datetime"
        if ptypes.is_numeric_dtype(series):
            return "numeric"
        return "categorical"

    def _numeric_summary(self, series: pd.Series) -> ProfileDict:
        """Compute numeric summary statistics for a column."""
        numeric_series = pd.to_numeric(series, errors="coerce")
        return {
            "min": self._safe_float(numeric_series.min()),
            "max": self._safe_float(numeric_series.max()),
            "mean": self._safe_float(numeric_series.mean()),
            "median": self._safe_float(numeric_series.median()),
            "std": self._safe_float(numeric_series.std()),
        }

    def _datetime_summary(self, series: pd.Series) -> ProfileDict:
        """Compute earliest and latest timestamps for a datetime column."""
        datetime_series = pd.to_datetime(series, errors="coerce")
        earliest = datetime_series.min()
        latest = datetime_series.max()
        return {
            "earliest": self._json_safe_value(earliest),
            "latest": self._json_safe_value(latest),
        }

    def _categorical_samples(self, series: pd.Series) -> ProfileDict:
        """Return the five most frequent categorical values."""
        value_counts = series.value_counts(dropna=True).head(self.CATEGORICAL_TOP_VALUE_COUNT)
        top_values: list[ProfileDict] = []
        for value, count in value_counts.items():
            top_values.append(
                {
                    "value": self._json_safe_value(value),
                    "count": int(count),
                }
            )
        return {"top_values": top_values}

    def _json_safe_sample_rows(self, sample_df: pd.DataFrame) -> list[ProfileDict]:
        """Convert a sample dataframe into JSON-serializable row dictionaries."""
        records: list[ProfileDict] = []
        for row in sample_df.to_dict(orient="records"):
            records.append(
                {str(column): self._json_safe_value(value) for column, value in row.items()}
            )
        return records

    def _json_safe_value(self, value: Any) -> Any:
        """Convert a single value into a JSON-serializable representation."""
        if value is None:
            return None

        if isinstance(value, pd.Timestamp):
            return value.isoformat()

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, np.datetime64):
            timestamp = pd.Timestamp(value)
            if pd.isna(timestamp):
                return None
            return timestamp.isoformat()

        if isinstance(value, np.bool_):
            return bool(value)

        if isinstance(value, np.integer):
            return int(value)

        if isinstance(value, np.floating):
            return self._safe_float(value)

        if isinstance(value, float):
            return self._safe_float(value)

        if pd.isna(value):
            return None

        if isinstance(value, (str, int, bool)):
            return value

        return str(value)

    def _safe_float(self, value: Any) -> float | None:
        """Convert a numeric value to a JSON-safe float or None."""
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None

        if not np.isfinite(numeric_value):
            return None

        return numeric_value
