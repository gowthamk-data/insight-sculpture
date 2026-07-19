"""Targeted unit tests for the planner refactor addressing five failure categories."""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ["LLM_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = "test"
os.environ["OPENAI_API_KEY"] = "test"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "true"

import pytest
from unittest.mock import MagicMock
from app.analytics.intent_extractor import _resolve_schema_references, extract_intent
from app.llm.intent_normalizer import extract_semantic_intent, SemanticIntent
from app.llm.planner import AnalysisPlanner
from app.schemas import AnalysisPlan, AllowedOperation, AggregationType, SortOrder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_planner():
    """Create an AnalysisPlanner with a mock LLM client."""
    from app.llm.openai_client import BaseLLMClient
    
    mock_client = MagicMock(spec=BaseLLMClient)
    mock_client.generate_json.return_value = AnalysisPlan(
        operation=AllowedOperation.SUMMARIZE,
        target_columns=[],
    )
    return AnalysisPlanner(mock_client)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dataset_profile():
    """Dataset profile matching run_planner_tests.py."""
    return {
        "shape": {"rows": 8, "columns": 35},
        "columns": {
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
            "Amount": {"inferred_type": "int64", "semantic_type": "numeric"},
        },
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
                "Paid": 500, "Course": "CS101", "EmployeeID": "E001",
            },
        ],
    }


# ---------------------------------------------------------------------------
# 1. Schema-Aware Entity Resolution
# ---------------------------------------------------------------------------

class TestSchemaAwareEntityResolution:
    """Case-insensitive matching, singular/plural normalization, alias support,
    and business entity filtering."""

    def test_case_insensitive_matching(self, dataset_profile):
        resolution = _resolve_schema_references("Sort by salary descending", dataset_profile)
        assert resolution.resolved is True

    def test_singular_plural_normalization(self, dataset_profile):
        resolution = _resolve_schema_references("Total sales by regions", dataset_profile)
        assert resolution.resolved is True

    def test_business_entities_filtered(self, dataset_profile):
        resolution = _resolve_schema_references("How many customers are there?", dataset_profile)
        assert resolution.resolved is True

    def test_unresolved_not_silently_discarded(self, dataset_profile):
        resolution = _resolve_schema_references("Sum NonExistentCol", dataset_profile)
        assert resolution.resolved is False
        assert "NonExistentCol" in resolution.missing_columns

    def test_stop_words_do_not_fail(self, dataset_profile):
        queries = [
            "What is the total sales?",
            "Show records where City = Chennai",
            "Sort by Date ascending",
            "Filter out nulls",
        ]
        for q in queries:
            resolution = _resolve_schema_references(q, dataset_profile)
            assert resolution.resolved is True, f"Failed for: {q}"


# ---------------------------------------------------------------------------
# 2. Intent-Driven LLM Prompting
# ---------------------------------------------------------------------------

class TestIntentDrivenPrompting:
    """Operational hints injected into LLM prompts."""

    def test_extract_semantic_intent_populates_hints(self, dataset_profile):
        raw = extract_intent("Total sales by Region")
        semantic = extract_semantic_intent("Total sales by Region", dataset_profile, raw)
        assert semantic.operation == "aggregate"
        assert len(semantic.hints) > 0

    def test_semantic_intent_resolves_columns(self, dataset_profile):
        raw = extract_intent("Average salary by Department")
        semantic = extract_semantic_intent("Average salary by Department", dataset_profile, raw)
        assert "Salary" in semantic.target_columns or "salary" in semantic.target_columns
        assert "Department" in semantic.group_by or "department" in semantic.group_by

    def test_intent_injection_into_prompt(self, dataset_profile):
        from app.llm.prompts import build_planner_user_prompt
        raw = extract_intent("Sort by Date ascending")
        semantic = extract_semantic_intent("Sort by Date ascending", dataset_profile, raw)
        prompt = build_planner_user_prompt("Sort by Date ascending", "dummy", semantic)
        assert "Operational Hints" in prompt
        assert "Sort by: Date" in prompt or "sort" in prompt.lower()


# ---------------------------------------------------------------------------
# 3. Post-Generation AnalysisPlan Normalization
# ---------------------------------------------------------------------------

class TestPostGenerationNormalization:
    """group_by removal from target_columns, correlation restriction, sort fix."""

    def test_group_by_removed_from_target_columns(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["Sales", "Region"],
            group_by=["Region"],
            aggregation=AggregationType.SUM,
        )
        normalized = planner._normalize_analysis_plan(plan, dataset_profile, "Total sales by Region")
        assert "Region" not in normalized.target_columns
        assert "Sales" in normalized.target_columns

    def test_correlation_restricted_to_numeric(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.CORRELATION,
            target_columns=["Sales", "Region"],
        )
        normalized = planner._normalize_analysis_plan(plan, dataset_profile, "Correlation Sales Region")
        assert "Region" not in normalized.target_columns
        assert "Sales" in normalized.target_columns

    def test_multi_column_sort_fixed(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Sales", "Profit"],
        )
        normalized = planner._normalize_analysis_plan(plan, dataset_profile, "Sort by Sales then Profit descending")
        assert normalized.sort_by == "Profit"
        assert normalized.sort_order == SortOrder.DESC


# ---------------------------------------------------------------------------
# 4. Ambiguity Resolution
# ---------------------------------------------------------------------------

class TestAmbiguityResolution:
    """Generic queries should not default to summarize when specific intent exists."""

    def test_generic_query_with_column_not_summarize(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.SUMMARIZE,
            target_columns=[],
        )
        # "Show records where City = Chennai" has "=" → filter operation detected
        normalized = planner._normalize_analysis_plan(plan, dataset_profile, "Show records where City = Chennai")
        assert normalized.operation == AllowedOperation.FILTER

    def test_explicit_keyword_overrides_summarize(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.SUMMARIZE,
        )
        normalized = planner._normalize_analysis_plan(plan, dataset_profile, "Total sales")
        assert normalized.operation == AllowedOperation.AGGREGATE


# ---------------------------------------------------------------------------
# 5. Regression Safety and Validation
# ---------------------------------------------------------------------------

class TestRegressionSafety:
    """Ensure existing validation remains intact."""

    def test_validation_accepts_valid_plan(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.AGGREGATE,
            aggregation=AggregationType.SUM,
            target_columns=["Sales"],
        )
        validated = planner._validate_analysis_plan(plan, dataset_profile)
        assert validated.operation == AllowedOperation.AGGREGATE

    def test_validation_rejects_invalid_columns(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.AGGREGATE,
            aggregation=AggregationType.SUM,
            target_columns=["NonExistent"],
        )
        with pytest.raises(Exception):
            planner._validate_analysis_plan(plan, dataset_profile)

    def test_aggregation_requirement_enforced(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.AGGREGATE,
            target_columns=["Sales"],
        )
        with pytest.raises(Exception):
            planner._validate_analysis_plan(plan, dataset_profile)

    def test_groupby_requires_group_by(self, dataset_profile):
        planner = _mock_planner()
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            aggregation=AggregationType.SUM,
            target_columns=["Sales"],
        )
        with pytest.raises(Exception):
            planner._validate_analysis_plan(plan, dataset_profile)
