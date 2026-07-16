"""Unit tests for deterministic schema validation of AnalysisPlan columns.

Run from the backend directory:
    cd backend
    python ../test_column_validation.py
"""

from __future__ import annotations

import difflib
import sys
import os

# Ensure the backend package is importable when running from the repo root
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

from app.core.exceptions import ColumnNotFoundError
from app.llm.openai_client import BaseLLMClient
from app.llm.planner import AnalysisPlanner
from app.schemas import FilterCondition, FilterOperator


class MockLLMClient(BaseLLMClient):
    """Minimal mock that satisfies the planner's isinstance check."""

    def generate_json(self, **kwargs):
        raise NotImplementedError("Mock does not generate plans")

    def stream_text(self, **kwargs):
        raise NotImplementedError("Mock does not stream text")

    def generate_text(self, **kwargs):
        raise NotImplementedError("Mock does not generate text")


def test_valid_columns_pass():
    """Valid columns must NOT raise any exception."""
    planner = AnalysisPlanner(llm_client=MockLLMClient())
    profile = {"columns": {"salary": {}, "name": {}, "age": {}}}

    # Should not raise
    planner._validate_columns_exist(["salary", "name"], profile)
    print("PASS: test_valid_columns_pass")


def test_missing_single_column_raises():
    """A single missing column in target_columns must raise ColumnNotFoundError."""
    planner = AnalysisPlanner(llm_client=MockLLMClient())
    profile = {"columns": {"salary": {}, "name": {}, "age": {}}}

    try:
        planner._validate_columns_exist(["salry"], profile)
        raise AssertionError("Expected ColumnNotFoundError was not raised")
    except ColumnNotFoundError as exc:
        d = exc.to_dict()
        assert d["error_code"] == "COLUMN_NOT_FOUND", f"Wrong error code: {d['error_code']}"
        assert "salry" in d["details"]["column"], f"Missing column not in details: {d['details']}"
        assert "salary" in d["details"]["available_columns"]
        # Fuzzy suggestion should be present
        assert "did_you_mean" in d["details"], "did_you_mean missing"
        assert "salary" in d["details"]["did_you_mean"].get("salry", [])
        print("PASS: test_missing_single_column_raises")


def test_missing_multiple_columns_raise():
    """Multiple missing columns must raise ColumnNotFoundError with all names."""
    planner = AnalysisPlanner(llm_client=MockLLMClient())
    profile = {"columns": {"salary": {}, "name": {}, "age": {}}}

    try:
        planner._validate_columns_exist(["salry", "nage"], profile)
        raise AssertionError("Expected ColumnNotFoundError was not raised")
    except ColumnNotFoundError as exc:
        d = exc.to_dict()
        missing = d["details"]["column"]
        assert isinstance(missing, list), f"Expected list of columns, got {type(missing)}"
        assert "salry" in missing
        assert "nage" in missing
        assert d["details"]["did_you_mean"]["salry"] == ["salary"]
        print("PASS: test_missing_multiple_columns_raise")


def test_no_fuzzy_match_when_unavailable():
    """If no close match exists, did_you_mean must be omitted or empty."""
    planner = AnalysisPlanner(llm_client=MockLLMClient())
    profile = {"columns": {"alpha": {}, "xyz": {}}}

    try:
        planner._validate_columns_exist(["gamma", "delta"], profile)
        raise AssertionError("Expected ColumnNotFoundError was not raised")
    except ColumnNotFoundError as exc:
        d = exc.to_dict()
        suggestions = d["details"].get("did_you_mean", {})
        # Neither missing column should have a strong match
        assert not suggestions.get("gamma")
        assert not suggestions.get("delta")
        print("PASS: test_no_fuzzy_match_when_unavailable")


def test_filter_column_missing_raises():
    """Missing column inside a FilterCondition must raise ColumnNotFoundError."""
    planner = AnalysisPlanner(llm_client=MockLLMClient())
    profile = {"columns": {"salary": {}, "name": {}, "age": {}}}

    try:
        planner._validate_filters(
            [FilterCondition(column="salry", operator=FilterOperator.GT, value=50000)],
            profile,
        )
        raise AssertionError("Expected ColumnNotFoundError was not raised")
    except ColumnNotFoundError as exc:
        d = exc.to_dict()
        assert d["details"]["did_you_mean"] == {"salry": ["salary"]}
        print("PASS: test_filter_column_missing_raises")


def test_error_response_structure():
    """ColumnNotFoundError must serialize to the expected API response shape."""
    exc = ColumnNotFoundError(
        column="salry",
        available_columns=["salary", "name", "age"],
        details={"did_you_mean": {"salry": ["salary"]}},
    )

    payload = exc.to_dict()
    assert payload["error_code"] == "COLUMN_NOT_FOUND"
    assert exc.http_status == 400
    assert payload["message"] == "Column not found: salry"
    assert payload["details"]["column"] == "salry"
    assert payload["details"]["available_columns"] == ["salary", "name", "age"]
    assert payload["details"]["did_you_mean"] == {"salry": ["salary"]}
    print("PASS: test_error_response_structure")


if __name__ == "__main__":
    test_valid_columns_pass()
    test_missing_single_column_raises()
    test_missing_multiple_columns_raise()
    test_no_fuzzy_match_when_unavailable()
    test_filter_column_missing_raises()
    test_error_response_structure()
    print("\nAll unit tests passed.")