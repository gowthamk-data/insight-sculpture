#!/usr/bin/env python3
"""Planner Capability Test Runner — validates the Analytics Planner against the
Planner Capability Matrix.

This is an independent QA utility that:
  - Extracts all planner test cases from the capability matrix
  - Executes each question through the planner
  - Compares the generated AnalysisPlan with expected fields
  - Records PASS/FAIL for every test
  - Continues execution even if individual tests fail
  - Generates a comprehensive report

Usage:
    cd backend && python -m tests.run_planner_tests

Or from project root:
    python backend/tests/run_planner_tests.py

Flags:
    --failed-only    Rerun only previously failed tests
    --tests TEST1,TEST2,...   Run specific tests by ID

Constraints:
    - Does NOT modify planner logic, prompts, executor, or schemas.
    - Does NOT change existing tests.
    - Builds the test runner as an independent QA utility.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import time

# Ensure backend is importable
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

os.environ["APP_NAME"] = "Insight Sculpture"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "true"
os.environ["LLM_PROVIDER"] = "gemini"
# os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "test-key-placeholder")
# os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "test-key-placeholder")
os.environ["LLM_MODEL"] = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
os.environ["HOST"] = "127.0.0.1"
os.environ["PORT"] = "8000"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers during test execution
logging.getLogger("app.llm.planner").setLevel(logging.WARNING)
logging.getLogger("app.llm.gemini_client").setLevel(logging.WARNING)
logging.getLogger("app.analytics.intent_extractor").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Retry configuration constants (mirrors LLM client configuration)
# ---------------------------------------------------------------------------

MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0  # seconds
RETRY_BACKOFF_MULTIPLIER = 2.0
FALLBACK_RATE_LIMIT_DELAY = 10.0  # seconds when Retry-After not provided

# ---------------------------------------------------------------------------
# Test case definitions — extracted from docs/PLANNER_CAPABILITY_MATRIX.md
# ---------------------------------------------------------------------------

CATEGORIES = [
    "Aggregation",
    "Filtering",
    "GroupBy",
    "Sorting",
    "Top N",
    "Correlation",
    "Mixed Queries",
    "Edge Cases",
]


@dataclass
class ExpectedFields:
    """Expected field values for a test case. None means 'do not validate this field'."""
    operation: str | None = None
    aggregation: str | None = None
    target_columns: list[str] | None = None
    group_by: list[str] | None = None
    filters: list[dict[str, Any]] | None = None
    sort_by: str | None = None
    sort_order: str | None = None
    limit: int | None = None
    chart_type: str | None = None
    explanation_required: bool | None = None


@dataclass
class TestCase:
    """A single test case extracted from the capability matrix."""
    id: str
    category: str
    question: str
    expected: ExpectedFields


@dataclass
class TestResult:
    """Result of executing a single test case."""
    test_id: str
    category: str
    question: str
    status: str  # PASS or FAIL
    failure_reason: str = ""
    actual_plan: dict[str, Any] | None = None
    expected_fields: ExpectedFields | None = None


@dataclass
class CategorySummary:
    """Summary of results for a category."""
    total: int = 0
    passed: int = 0
    failed: int = 0


# ---------------------------------------------------------------------------
# Define all test cases from the capability matrix
# ---------------------------------------------------------------------------

ALL_TEST_CASES: list[TestCase] = []

# --- Aggregation tests (8 tests) ---
_agg_cases = [
    ("AGG-01", "What is the total sales?", "aggregate", "sum", ["Sales"]),
    ("AGG-02", "Calculate the average salary", "aggregate", "mean", ["Salary"]),
    ("AGG-03", "What is the mean temperature?", "aggregate", "mean", ["Temperature"]),
    ("AGG-04", "Find the median house price", "aggregate", "median", ["Price"]),
    ("AGG-05", "How many customers are there?", "aggregate", "count", ["CustomerID"]),
    ("AGG-06", "What is the minimum score?", "aggregate", "min", ["Score"]),
    ("AGG-07", "What is the maximum profit?", "aggregate", "max", ["Profit"]),
    ("AGG-08", "What is the standard deviation of returns?", "aggregate", "std", ["Returns"]),
]
for tid, q, op, agg, cols in _agg_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Aggregation", question=q,
        expected=ExpectedFields(operation=op, aggregation=agg, target_columns=cols),
    ))

# --- Filtering tests (7 tests) ---
_filter_cases = [
    ("FIL-01", "Show records where City = Chennai", [{"column": "City", "operator": "=", "value": "Chennai"}]),
    ("FIL-02", "Exclude rows where Status = cancelled", [{"column": "Status", "operator": "!=", "value": "cancelled"}]),
    ("FIL-03", "Show sales greater than 1000", [{"column": "Sales", "operator": ">", "value": 1000}]),
    ("FIL-04", "Show records where age < 30", [{"column": "age", "operator": "<", "value": 30}]),
    ("FIL-05", "Show orders with amount >= 500", [{"column": "amount", "operator": ">=", "value": 500}]),
    ("FIL-06", "Show employees with salary <= 75000", [{"column": "salary", "operator": "<=", "value": 75000}]),
    ("FIL-07", "Show customers with name containing Smith", [{"column": "name", "operator": "contains", "value": "Smith"}]),
]
for tid, q, filters in _filter_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Filtering", question=q,
        expected=ExpectedFields(operation="filter", filters=filters),
    ))

# --- GroupBy tests (6 tests) ---
_group_cases = [
    ("GRP-01", "Total sales by Region", "groupby", ["Region"], "sum", ["Sales"]),
    ("GRP-02", "Average salary by Department", "groupby", ["Department"], "mean", ["Salary"]),
    ("GRP-03", "Count of orders by Customer", "groupby", ["Customer"], "count", ["OrderID"]),
    ("GRP-04", "Median price by Category", "groupby", ["Category"], "median", ["Price"]),
    ("GRP-05", "Total sales by Region and Segment", "groupby", ["Region", "Segment"], "sum", ["Sales"]),
    ("GRP-06", "Average score by Grade and Subject", "groupby", ["Grade", "Subject"], "mean", ["Score"]),
]
for tid, q, op, group, agg, cols in _group_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="GroupBy", question=q,
        expected=ExpectedFields(operation=op, group_by=group, aggregation=agg, target_columns=cols),
    ))

# --- Sorting tests (5 tests) ---
_sort_cases = [
    ("SRT-01", "Sort by Date ascending", "sort", "Date", "asc"),
    ("SRT-02", "Sort by Salary descending", "sort", "Salary", "desc"),
    ("SRT-03", "Order by Name A to Z", "sort", "Name", "asc"),
    ("SRT-04", "Order by Score high to low", "sort", "Score", "desc"),
    ("SRT-05", "Sort by Department then Salary descending", "sort", "Salary", "desc"),
]
for tid, q, op, sort_by, sort_order in _sort_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Sorting", question=q,
        expected=ExpectedFields(operation=op, sort_by=sort_by, sort_order=sort_order),
    ))

# --- Top N tests (4 tests) ---
_top_cases = [
    ("TOP-01", "Top 10 customers by sales", "top_n", "Sales", "desc", 10),
    ("TOP-02", "Bottom 5 products by rating", "top_n", "Rating", "asc", 5),
    ("TOP-03", "Top 3 highest paid employees", "top_n", "Salary", "desc", 3),
    ("TOP-04", "Lowest 10 transaction amounts", "top_n", "amount", "asc", 10),
]
for tid, q, op, sort_by, sort_order, limit in _top_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Top N", question=q,
        expected=ExpectedFields(operation=op, sort_by=sort_by, sort_order=sort_order, limit=limit),
    ))

# --- Correlation tests (2 tests) ---
_corr_cases = [
    ("COR-01", "Correlation between Age and Income", ["Age", "Income"]),
    ("COR-02", "Show correlation matrix for all numeric columns", ["Age", "Income", "Score"]),
]
for tid, q, cols in _corr_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Correlation", question=q,
        expected=ExpectedFields(operation="correlation", target_columns=cols),
    ))

# --- Mixed Queries tests (15 tests) ---
_mix_cases = [
    ("MIX-01", "Top 10 customers by total sales",
     ExpectedFields(operation="top_n", sort_by="Sales", sort_order="desc", limit=10,
                     group_by=["Customer"], aggregation="sum", target_columns=["Sales"])),
    ("MIX-02", "Average salary by department sorted descending",
     ExpectedFields(operation="groupby", group_by=["Department"], aggregation="mean",
                     target_columns=["Salary"], sort_by="Salary", sort_order="desc")),
    ("MIX-03", "Total sales for customers in Chennai",
     ExpectedFields(operation="aggregate", filters=[{"column": "City", "operator": "=", "value": "Chennai"}],
                     aggregation="sum", target_columns=["Sales"])),
    ("MIX-04", "Count of orders by Region where Amount > 1000",
     ExpectedFields(operation="groupby", group_by=["Region"], aggregation="count",
                     target_columns=["OrderID"], filters=[{"column": "Amount", "operator": ">", "value": 1000}])),
    ("MIX-05", "Top 5 products by sales in Electronics category",
     ExpectedFields(operation="top_n", sort_by="Sales", sort_order="desc", limit=5,
                     group_by=["Product"], aggregation="sum", target_columns=["Sales"],
                     filters=[{"column": "Category", "operator": "=", "value": "Electronics"}])),
    ("MIX-06", "Average salary by department for employees in Mumbai",
     ExpectedFields(operation="groupby", group_by=["Department"], aggregation="mean",
                     target_columns=["Salary"], filters=[{"column": "City", "operator": "=", "value": "Mumbai"}])),
    ("MIX-07", "Show top 20 transactions sorted by date",
     ExpectedFields(operation="top_n", sort_by="Date", sort_order="desc", limit=20)),
    ("MIX-08", "Total revenue by month for 2024",
     ExpectedFields(operation="groupby", group_by=["Month"], aggregation="sum",
                     target_columns=["Revenue"], filters=[{"column": "Year", "operator": "=", "value": 2024}])),
    ("MIX-09", "Correlation between Marketing Spend and Revenue by Region",
     ExpectedFields(operation="correlation", target_columns=["Marketing Spend", "Revenue"], group_by=["Region"])),
    ("MIX-10", "Show customers with more than 5 orders",
     ExpectedFields(operation="filter", filters=[{"column": "OrderCount", "operator": ">", "value": 5}])),
    ("MIX-11", "Top 10 states by population",
     ExpectedFields(operation="top_n", sort_by="Population", sort_order="desc", limit=10,
                     group_by=["State"], aggregation="sum", target_columns=["Population"])),
    ("MIX-12", "Average order value by customer segment",
     ExpectedFields(operation="groupby", group_by=["Segment"], aggregation="mean", target_columns=["OrderValue"])),
    ("MIX-13", "Show the highest paid employee in each department",
     ExpectedFields(operation="groupby", group_by=["Department"], aggregation="max", target_columns=["Salary"])),
    ("MIX-14", "Number of transactions per day for the last week",
     ExpectedFields(operation="groupby", group_by=["Date"], aggregation="count", target_columns=["TransactionID"])),
    ("MIX-15", "Products with price between 100 and 500 sorted by rating",
     ExpectedFields(operation="sort", filters=[{"column": "Price", "operator": ">=", "value": 100},
                                             {"column": "Price", "operator": "<=", "value": 500}],
                      sort_by="Rating", sort_order="desc")),
]
for tid, q, expected in _mix_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Mixed Queries", question=q, expected=expected,
    ))

# --- Edge Cases tests (15 tests) ---
_edge_cases = [
    ("EDGE-01", "How much money was collected?",
     ExpectedFields(operation="aggregate")),
    ("EDGE-02", "Which course generated the highest revenue?",
     ExpectedFields(operation="groupby", group_by=["Course"], aggregation="sum", target_columns=["Revenue"])),
    ("EDGE-03", "Show me everything",
     ExpectedFields(operation="summarize")),
    ("EDGE-04", "Give me the data",
     ExpectedFields(operation="summarize")),
    ("EDGE-05", "List all records",
     ExpectedFields(operation="filter")),
    ("EDGE-06", "What is the average?",
     ExpectedFields(operation="aggregate", aggregation="mean")),
    ("EDGE-07", "Group by",
     ExpectedFields(operation="groupby")),
    ("EDGE-08", "Top N",
     ExpectedFields(operation="top_n")),
    ("EDGE-09", "Sales by region over time",
     ExpectedFields(operation="groupby", group_by=["Region"], aggregation="sum", target_columns=["Sales"])),
    ("EDGE-10", "Compare Age and Income",
     ExpectedFields(operation="correlation", target_columns=["Age", "Income"])),
    ("EDGE-11", "Show paid amount",
     ExpectedFields(operation="filter", target_columns=["Paid"])),
    ("EDGE-12", "Total salary by course",
     ExpectedFields(operation="groupby", group_by=["Course"], aggregation="sum", target_columns=["Salary"])),
    ("EDGE-13", "Average of all numeric columns",
     ExpectedFields(operation="aggregate", aggregation="mean")),
    ("EDGE-14", "Filter out nulls",
     ExpectedFields(operation="filter")),
    ("EDGE-15", "Show me the top and bottom 5",
     ExpectedFields(operation="top_n", limit=5)),
]
for tid, q, expected in _edge_cases:
    ALL_TEST_CASES.append(TestCase(
        id=tid, category="Edge Cases", question=q, expected=expected,
    ))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def normalize_value(val: Any) -> Any:
    """Normalize values for comparison (e.g., string case for enums)."""
    if isinstance(val, str):
        return val.lower().strip()
    if isinstance(val, list):
        # Normalize each element in lists
        return [normalize_value(v) for v in val]
    if isinstance(val, dict):
        return {k: normalize_value(v) for k, v in val.items()}
    return val


def validate_filters(actual: list[dict[str, Any]] | None,
                     expected: list[dict[str, Any]] | None) -> tuple[bool, str]:
    """Validate filter conditions. Returns (passed, reason)."""
    if expected is None:
        return True, ""  # Skip validation if not specified

    actual_filters = actual or []
    expected_filters = expected or []

    if len(actual_filters) != len(expected_filters):
        return False, (
            f"Filter count mismatch: expected {len(expected_filters)}, "
            f"got {len(actual_filters)}"
        )

    for i, (act, exp) in enumerate(zip(actual_filters, expected_filters)):
        for key in ["column", "operator"]:
            act_val = normalize_value(act.get(key))
            exp_val = normalize_value(exp.get(key))
            if act_val != exp_val:
                return False, (
                    f"Filter[{i}].{key}: expected '{exp_val}', got '{act_val}'"
                )

        # Value comparison - compare as strings to handle type differences
        act_val = str(normalize_value(act.get("value", "")))
        exp_val = str(normalize_value(exp.get("value", "")))
        if act_val != exp_val:
            return False, (
                f"Filter[{i}].value: expected '{exp_val}', got '{act_val}'"
            )

    return True, ""


def validate_plan(plan: dict[str, Any],
                  expected: ExpectedFields) -> tuple[bool, str]:
    """Validate an actual plan against expected fields. Returns (passed, reason)."""
    failures = []

    # Validate operation
    if expected.operation is not None:
        act_op = normalize_value(plan.get("operation", ""))
        exp_op = normalize_value(expected.operation)
        if act_op != exp_op:
            failures.append(f"operation: expected '{exp_op}', got '{act_op}'")

    # Validate aggregation
    if expected.aggregation is not None:
        act_agg = normalize_value(plan.get("aggregation"))
        exp_agg = normalize_value(expected.aggregation)
        if act_agg != exp_agg:
            failures.append(f"aggregation: expected '{exp_agg}', got '{act_agg}'")

    # Validate target_columns
    if expected.target_columns is not None:
        act_cols = normalize_value(plan.get("target_columns", []))
        exp_cols = normalize_value(expected.target_columns)
        if set(act_cols) != set(exp_cols):
            failures.append(
                f"target_columns: expected {exp_cols}, got {act_cols}"
            )

    # Validate group_by
    if expected.group_by is not None:
        act_group = normalize_value(plan.get("group_by", []))
        exp_group = normalize_value(expected.group_by)
        if set(act_group) != set(exp_group):
            failures.append(
                f"group_by: expected {exp_group}, got {act_group}"
            )

    # Validate filters
    if expected.filters is not None:
        passed, reason = validate_filters(
            plan.get("filters", []), expected.filters
        )
        if not passed:
            failures.append(reason)

    # Validate sort_by
    if expected.sort_by is not None:
        act_sort = normalize_value(plan.get("sort_by"))
        exp_sort = normalize_value(expected.sort_by)
        if act_sort != exp_sort:
            failures.append(f"sort_by: expected '{exp_sort}', got '{act_sort}'")

    # Validate sort_order
    if expected.sort_order is not None:
        act_order = normalize_value(plan.get("sort_order"))
        exp_order = normalize_value(expected.sort_order)
        if act_order != exp_order:
            failures.append(
                f"sort_order: expected '{exp_order}', got '{act_order}'"
            )

    # Validate limit
    if expected.limit is not None:
        act_limit = plan.get("limit")
        if act_limit != expected.limit:
            failures.append(
                f"limit: expected {expected.limit}, got {act_limit}"
            )

    # Validate chart_type
    if expected.chart_type is not None:
        act_chart = normalize_value(plan.get("chart_type", "none"))
        exp_chart = normalize_value(expected.chart_type)
        if act_chart != exp_chart:
            failures.append(
                f"chart_type: expected '{exp_chart}', got '{act_chart}'"
            )

    # Validate explanation_required
    if expected.explanation_required is not None:
        act_explain = plan.get("explanation_required")
        if act_explain != expected.explanation_required:
            failures.append(
                f"explanation_required: expected {expected.explanation_required}, "
                f"got {act_explain}"
            )

    if failures:
        return False, "; ".join(failures)

    return True, ""


# ---------------------------------------------------------------------------
# Dataset profile for testing
# ---------------------------------------------------------------------------

def build_test_dataset_profile() -> dict[str, Any]:
    """Build a dataset profile that includes all columns referenced in test cases."""
    columns = {
        "Sales": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Profit": {"inferred_type": "int64", "semantic_type": "numeric"},
        "City": {"inferred_type": "object", "semantic_type": "categorical"},
        "Status": {"inferred_type": "object", "semantic_type": "categorical"},
        "age": {"inferred_type": "int64", "semantic_type": "numeric"},
        "amount": {"inferred_type": "int64", "semantic_type": "numeric"},
        "salary": {"inferred_type": "int64", "semantic_type": "numeric"},
        "name": {"inferred_type": "object", "semantic_type": "categorical"},
        "Price": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Score": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Temperature": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Returns": {"inferred_type": "float64", "semantic_type": "numeric"},
        "CustomerID": {"inferred_type": "object", "semantic_type": "categorical"},
        "Customer": {"inferred_type": "object", "semantic_type": "categorical"},
        "OrderID": {"inferred_type": "object", "semantic_type": "categorical"},
        "Region": {"inferred_type": "object", "semantic_type": "categorical"},
        "Department": {"inferred_type": "object", "semantic_type": "categorical"},
        "Location": {"inferred_type": "object", "semantic_type": "categorical"},
        "Category": {"inferred_type": "object", "semantic_type": "categorical"},
        "Product": {"inferred_type": "object", "semantic_type": "categorical"},
        "Month": {"inferred_type": "object", "semantic_type": "categorical"},
        "Year": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Revenue": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Marketing Spend": {"inferred_type": "int64", "semantic_type": "numeric"},
        "OrderCount": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Population": {"inferred_type": "int64", "semantic_type": "numeric"},
        "State": {"inferred_type": "object", "semantic_type": "categorical"},
        "Segment": {"inferred_type": "object", "semantic_type": "categorical"},
        "OrderValue": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Date": {"inferred_type": "object", "semantic_type": "datetime"},
        "Rating": {"inferred_type": "float64", "semantic_type": "numeric"},
        "Grade": {"inferred_type": "object", "semantic_type": "categorical"},
        "Subject": {"inferred_type": "object", "semantic_type": "categorical"},
        "TransactionID": {"inferred_type": "object", "semantic_type": "categorical"},
        "Paid": {"inferred_type": "int64", "semantic_type": "numeric"},
        "Course": {"inferred_type": "object", "semantic_type": "categorical"},
        "EmployeeID": {"inferred_type": "object", "semantic_type": "categorical"},
        "Income": {"inferred_type": "int64", "semantic_type": "numeric"},
    }

    profile = {
        "shape": {"rows": 8, "columns": len(columns)},
        "columns": columns,
        "sample_rows": [
            {
                "Sales": 1000, "Profit": 200, "City": "Chennai", "Status": "active",
                "age": 25, "amount": 500, "salary": 50000, "name": "John",
                "Price": 100, "Score": 85, "Temperature": 30, "Returns": 0.05,
                "CustomerID": "C001", "OrderID": "ORD001", "Region": "North",
                "Department": "Engineering", "Location": "New York",
                "Category": "Electronics", "Product": "Widget A",
                "Month": "Jan", "Year": 2024, "Revenue": 50000,
                "Marketing Spend": 10000, "OrderCount": 5,
                "Population": 1000000, "State": "California", "Segment": "Consumer",
                "OrderValue": 250, "Date": "2024-01-15", "Rating": 4.5,
                "Grade": "A", "Subject": "Math", "TransactionID": "TXN001",
                "Paid": 500, "Course": "CS101", "EmployeeID": "E001", "Income": 60000,
            },
        ],
    }
    return profile


# ---------------------------------------------------------------------------
# Planner initialization
# ---------------------------------------------------------------------------

def create_planner():
    """Create an AnalysisPlanner instance configured for testing."""
    from app.llm.gemini_client import GeminiClient
    from app.llm.planner import AnalysisPlanner

    llm_client = GeminiClient()
    planner = AnalysisPlanner(llm_client)
    return planner


# ---------------------------------------------------------------------------
# Retry helper and error detection utilities
# ---------------------------------------------------------------------------

def is_retryable_error(exc: Exception) -> bool:
    """Determine if an exception should be retried.
    
    Retries on: HTTP 429 errors, network failures, timeout errors.
    Does NOT retry on: authentication errors, validation errors, JSON errors.
    
    Args:
        exc: The exception to check.
        
    Returns:
        True if the error should be retried, False otherwise.
    """
    error_str = str(exc).lower()
    
    # Import application exceptions for type checking
    from app.llm.client import AuthenticationError, RateLimitError, NetworkError, TimeoutError
    
    # Check by type first
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, NetworkError):
        return True
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, AuthenticationError):
        return False
    
    # Check for rate limit indicators in error message
    if "429" in error_str or "resource_exhausted" in error_str or "rate limit" in error_str:
        return True
    
    # Check for network indicators
    if "connection" in error_str or "network" in error_str:
        return True
    
    # Check for timeout indicators
    if "timeout" in error_str:
        return True
    
    return False


def get_retry_after_delay(exc: Exception) -> float | None:
    """Extract Retry-After delay from exception if available.
    
    Args:
        exc: The exception to extract delay from.
        
    Returns:
        Delay in seconds from Retry-After header, or None if not found.
    """
    # Try to get Retry-After from various exception types
    if hasattr(exc, 'response') and exc.response is not None:
        response = exc.response
        if hasattr(response, 'headers'):
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass
    
    # Check for retry_delay in Gemini-style exceptions
    if hasattr(exc, 'retry_delay'):
        retry_delay = getattr(exc, 'retry_delay', None)
        if retry_delay is not None:
            if hasattr(retry_delay, 'seconds'):
                return float(retry_delay.seconds)
            try:
                return float(retry_delay)
            except (ValueError, TypeError):
                pass
    
    return None


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def is_rate_limit_error(exc: Exception) -> bool:
    """Determine if an exception is specifically a rate limit error.
    
    Args:
        exc: The exception to check.
        
    Returns:
        True if the error is a rate limit error, False otherwise.
    """
    error_str = str(exc).lower()
    
    # Import application exceptions for type checking
    from app.llm.client import RateLimitError
    
    if isinstance(exc, RateLimitError):
        return True
    
    if "429" in error_str or "resource_exhausted" in error_str or "rate limit" in error_str:
        return True
    
    return False


def run_test(
    test_case: TestCase,
    planner: Any,
    dataset_profile: dict[str, Any],
) -> TestResult:
    """Execute a single test case through the planner and validate the result.
    
    Uses adaptive rate-limiting with exponential backoff for retryable errors.
    
    Args:
        test_case: The test case to execute.
        planner: The analysis planner instance.
        dataset_profile: Dataset profile for the planner.
        
    Returns:
        TestResult with PASS/FAIL status and details.
    """
    result = TestResult(
        test_id=test_case.id,
        category=test_case.category,
        question=test_case.question,
        status="FAIL",
        expected_fields=test_case.expected,
    )

    delay = INITIAL_RETRY_DELAY
    analysis_plan = None
    last_wait_time: float | None = None  # Track actual wait time for logging

    for attempt in range(MAX_RETRIES + 1):
        try:
            analysis_plan = planner.plan(
                user_question=test_case.question,
                dataset_profile=dataset_profile,
                conversation_history=None,
            )
            
            # Check if this was a retry attempt
            if attempt > 0 and last_wait_time is not None:
                logger.info(
                    f"  [RETRY] Test {test_case.id} attempt {attempt + 1}/{MAX_RETRIES + 1}: "
                    f"Retry successful after {last_wait_time:.1f}s wait"
                )
            break

        except Exception as exc:
            # Check if this is a retryable error with retries remaining
            if is_retryable_error(exc) and attempt < MAX_RETRIES:
                # Determine wait duration based on error type
                retry_after = get_retry_after_delay(exc)
                if retry_after is not None:
                    wait_time = retry_after
                    retry_reason = f"Retry-After header detected ({retry_after:.1f}s)"
                elif is_rate_limit_error(exc):
                    wait_time = FALLBACK_RATE_LIMIT_DELAY
                    retry_reason = f"Rate limit error, using fallback delay ({FALLBACK_RATE_LIMIT_DELAY}s)"
                else:
                    wait_time = delay
                    retry_reason = f"Transient error (network/timeout), retrying in {delay:.1f}s"
                
                logger.info(
                    f"  [RETRY] Test {test_case.id} attempt {attempt + 1}/{MAX_RETRIES + 1}: "
                    f"Reason: {retry_reason}. "
                    f"Waiting {wait_time:.1f}s before retry..."
                )
                
                time.sleep(wait_time)
                last_wait_time = wait_time  # Store for success logging
                delay *= RETRY_BACKOFF_MULTIPLIER
                continue
            
            # Non-retryable error or exhausted retries - record failure and stop retrying
            if attempt > 0:
                logger.warning(
                    f"  [RETRY] Test {test_case.id} attempt {attempt + 1}/{MAX_RETRIES + 1}: "
                    f"Retry exhausted. Error: {type(exc).__name__}: {exc}"
                )
            # Record the failure reason (non-retryable or all retries exhausted)
            result.failure_reason = f"{type(exc).__name__}: {exc}"
            # Return early - don't re-raise, let the test continue to next case
            return result

    # Process the result
    if analysis_plan is None:
        # This happens when all retries were exhausted - last_exception was recorded
        return result

    try:
        plan_dict = (
            analysis_plan.model_dump()
            if hasattr(analysis_plan, "model_dump")
            else analysis_plan.dict()
        )

        result.actual_plan = plan_dict

        passed, reason = validate_plan(
            plan_dict,
            test_case.expected,
        )

        if passed:
            result.status = "PASS"
        else:
            result.failure_reason = reason

    except Exception as exc:
        result.failure_reason = (
            f"Planner raised {type(exc).__name__}: {exc}"
        )

        if hasattr(exc, "__traceback__"):
            tb = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )

            if len(tb) > 8:
                tb = tb[:3] + ["...\n"] + tb[-4:]

            result.failure_reason += "\n" + "".join(tb)

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[TestResult]) -> str:
    """Generate a comprehensive test report."""
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = total - passed
    pass_pct = (passed / total * 100) if total > 0 else 0.0

    # Build category summaries
    category_results: dict[str, list[TestResult]] = {}
    for r in results:
        category_results.setdefault(r.category, []).append(r)

    lines = []
    lines.append("=" * 72)
    lines.append("  Planner Capability Test Runner - Report")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 72)
    lines.append("")

    # Summary header
    lines.append("OVERALL SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Total Tests : {total}")
    lines.append(f"  Passed      : {passed}")
    lines.append(f"  Failed      : {failed}")
    lines.append(f"  Pass Rate   : {pass_pct:.1f}%")
    lines.append("")

    # Category summaries
    lines.append("SUMMARY BY CATEGORY")
    lines.append("-" * 40)
    for cat in CATEGORIES:
        cat_results = category_results.get(cat, [])
        cat_total = len(cat_results)
        cat_passed = sum(1 for r in cat_results if r.status == "PASS")
        cat_failed = cat_total - cat_passed
        cat_pct = (cat_passed / cat_total * 100) if cat_total > 0 else 0.0
        status_icon = "✓" if cat_failed == 0 else "✗"
        lines.append(f"  {status_icon} {cat:20s}: {cat_passed:2d}/{cat_total:2d} ({cat_pct:5.1f}%)")
    lines.append("")

    # Per-test results
    lines.append("PER-TEST RESULTS")
    lines.append("-" * 72)

    for r in results:
        status_tag = "[PASS]" if r.status == "PASS" else "[FAIL]"
        lines.append(f"  {status_tag} {r.test_id:8s} | {r.question[:60]}")
        if r.status == "FAIL" and r.failure_reason:
            lines.append(f"           Reason: {r.failure_reason}")
        if r.status == "FAIL" and r.actual_plan:
            # Show what the planner actually produced
            plan_json = json.dumps(r.actual_plan, indent=2)
            lines.append(f"           Actual Plan: {plan_json}")
        lines.append("")

    # Footer
    lines.append("=" * 72)
    lines.append(f"  End of Report — {passed}/{total} passed ({pass_pct:.1f}%)")
    lines.append("=" * 72)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Path to store failed test IDs for --failed-only functionality
FAILED_TESTS_CACHE = Path(__file__).resolve().parent / ".failed_tests_cache.json"


def load_failed_tests() -> list[str]:
    """Load previously failed test IDs from cache file."""
    if FAILED_TESTS_CACHE.exists():
        try:
            content = FAILED_TESTS_CACHE.read_text(encoding="utf-8")
            return json.loads(content)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_failed_tests(failed_ids: list[str]) -> None:
    """Save failed test IDs to cache file."""
    FAILED_TESTS_CACHE.write_text(json.dumps(failed_ids), encoding="utf-8")


def main():
    """Run all planner capability tests and print the report."""
    parser = argparse.ArgumentParser(
        description="Run planner capability benchmark tests"
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Rerun only previously failed tests",
    )
    parser.add_argument(
        "--tests",
        type=str,
        default=None,
        help="Run specific tests by ID (comma-separated, e.g., GRP-03,SRT-05)",
    )
    args = parser.parse_args()

    # Determine which tests to run
    test_ids_to_run: set[str] | None = None
    
    if args.failed_only:
        test_ids_to_run = set(load_failed_tests())
        if not test_ids_to_run:
            print("No previously failed tests found. Run without --failed-only first.")
            return 0
    elif args.tests:
        test_ids_to_run = set(tid.strip() for tid in args.tests.split(",") if tid.strip())

    # Filter test cases
    if test_ids_to_run is not None:
        test_cases = [tc for tc in ALL_TEST_CASES if tc.id in test_ids_to_run]
        if not test_cases:
            print(f"No tests found matching IDs: {test_ids_to_run}")
            return 1
    else:
        test_cases = ALL_TEST_CASES

    print("Initializing planner and dataset profile...")
    print()

    # Build dataset profile
    dataset_profile = build_test_dataset_profile()

    # Create planner
    try:
        planner = create_planner()

        print("  Planner initialized successfully")
        print(f"  Test cases: {len(test_cases)}")

    except Exception as exc:
        print(f"  FAILED to initialize planner: {exc}")
        print()
        print("ERROR: Planner initialization failed.")
        print("  - Check backend/.env for API keys")
        print("  - Ensure required packages are installed:")
        print("      pip install -r backend/requirements.txt")
        sys.exit(1)

    print()
    print("Running tests...")
    print()

    results: list[TestResult] = []
    total = len(test_cases)

    for i, test_case in enumerate(test_cases, start=1):

        result = run_test(
            test_case=test_case,
            planner=planner,
            dataset_profile=dataset_profile,
        )

        results.append(result)

        print(
            f"  [{i:3d}/{total:3d}] "
            f"{result.status:<7} "
            f"{result.test_id:8s} | "
            f"{result.question[:55]}"
        )
        
        # NO FIXED DELAY - requests run at maximum speed, only pausing when rate-limited

    print()
    print("Generating report...")
    print()

    report = generate_report(results)

    report_path = (
        Path(__file__).resolve().parent / "planner_test_report.txt"
    )

    report_path.write_text(
        report,
        encoding="utf-8",
    )

    print(f"  Report saved to: {report_path}")
    print()

    # Print report
    print(report)

    # Save failed test IDs for --failed-only
    failed_ids = [r.test_id for r in results if r.status == "FAIL"]
    save_failed_tests(failed_ids)

    # Summary
    passed_count = sum(r.status == "PASS" for r in results)
    failed_count = sum(r.status == "FAIL" for r in results)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total Tests : {total}")
    print(f"Passed      : {passed_count}")
    print(f"Failed      : {failed_count}")
    print("=" * 70)

    # Only genuine planner failures should fail the benchmark
    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())