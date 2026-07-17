"""Unit tests for the deterministic schema resolution layer.

Run from the backend directory:
    cd backend
    python -m pytest tests/test_intent_extractor.py -v
"""

from __future__ import annotations

import sys
import os

# Ensure the backend package is importable when running from the repo root
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BACKEND_DIR))

import pytest

from app.analytics.intent_extractor import (
    AGGREGATIONS,
    FILTER,
    GROUP_BY,
    SORT,
    TOP_BOTTOM,
    IntentReference,
    SchemaResolution,
    extract_intent,
    resolve_schema_references,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_profile() -> dict[str, Any]:
    """Dataset profile with columns: Paid, Student, Course, Date, Transaction."""
    return {
        "shape": {"rows": 100, "columns": 5},
        "columns": {
            "Paid": {"semantic_type": "numeric"},
            "Student": {"semantic_type": "string"},
            "Course": {"semantic_type": "string"},
            "Date": {"semantic_type": "datetime"},
            "Transaction": {"semantic_type": "string"},
        },
        "sample_rows": [
            {"Paid": 100, "Student": "Alice", "Course": "Math", "Date": "2024-01-01", "Transaction": "TXN1"},
            {"Paid": 200, "Student": "Bob", "Course": "Science", "Date": "2024-01-02", "Transaction": "TXN2"},
        ],
    }


@pytest.fixture
def minimal_profile() -> dict[str, Any]:
    """Dataset profile with only column names (no metadata)."""
    return {
        "shape": {"rows": 10, "columns": 2},
        "columns": {
            "alpha": {},
            "beta": {},
        },
    }


# ---------------------------------------------------------------------------
# extract_intent tests
# ---------------------------------------------------------------------------

class TestExtractIntent:
    """Tests for the deterministic intent extraction parser."""

    def test_aggregation_explicit_valid(self):
        """Explicit aggregation with a valid operand should be detected."""
        intent = extract_intent("Sum Paid")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_aggregation_synonym_total(self):
        """Synonym 'total' should map to aggregate."""
        intent = extract_intent("Total Paid")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_aggregation_synonym_avg(self):
        """Synonym 'avg' should map to aggregate."""
        intent = extract_intent("Avg Paid")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_aggregation_synonym_mean(self):
        """Synonym 'mean' should map to aggregate."""
        intent = extract_intent("Mean Paid")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_aggregation_synonym_count(self):
        """Synonym 'count' should map to aggregate."""
        intent = extract_intent("Count Student")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Student"]

    def test_aggregation_synonym_min(self):
        """Synonym 'min' should map to aggregate."""
        intent = extract_intent("Min Paid")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_aggregation_synonym_max(self):
        """Synonym 'max' should map to aggregate."""
        intent = extract_intent("Max Paid")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_group_by_explicit(self):
        """Explicit 'group by' should be detected."""
        intent = extract_intent("Group by Course")
        assert intent.operation == "groupby"
        assert intent.operands == ["Course"]

    def test_group_by_single_word_group(self):
        """Single word 'group' should map to groupby."""
        intent = extract_intent("Group Course")
        assert intent.operation == "groupby"
        assert intent.operands == ["Course"]

    def test_sort_by_explicit(self):
        """Explicit 'sort by' should be detected."""
        intent = extract_intent("Sort by Paid")
        assert intent.operation == "sort"
        assert intent.operands == ["Paid"]

    def test_sort_by_synonym_order_by(self):
        """Synonym 'order by' should map to sort."""
        intent = extract_intent("Order by Date")
        assert intent.operation == "sort"
        assert intent.operands == ["Date"]

    def test_top_n_highest(self):
        """'Highest' should map to top_n."""
        intent = extract_intent("Highest Paid")
        assert intent.operation == "top_n"
        assert intent.operands == ["Paid"]

    def test_top_n_lowest(self):
        """'Lowest' should map to top_n."""
        intent = extract_intent("Lowest Paid")
        assert intent.operation == "top_n"
        assert intent.operands == ["Paid"]

    def test_filter_equals(self):
        """'equals' should map to filter."""
        intent = extract_intent("Course equals Math")
        assert intent.operation == "filter"
        assert intent.operands == ["Course"]

    def test_filter_greater_than(self):
        """'greater than' should map to filter."""
        intent = extract_intent("Paid greater than 100")
        assert intent.operation == "filter"
        assert intent.operands == ["Paid"]

    def test_filter_contains(self):
        """'contains' should map to filter."""
        intent = extract_intent("Student contains Al")
        assert intent.operation == "filter"
        assert intent.operands == ["Student"]

    def test_natural_language_returns_empty(self):
        """Purely natural language questions must return empty operands."""
        intent = extract_intent("How much money was collected?")
        assert intent.operation is None
        assert intent.operands == []

    def test_natural_language_no_keyword(self):
        """Questions without operation keywords must return empty operands."""
        intent = extract_intent("What is the average value?")
        assert intent.operation is None
        assert intent.operands == []

    def test_empty_question(self):
        """Empty or whitespace-only questions must return empty intent."""
        intent = extract_intent("")
        assert intent.operation is None
        assert intent.operands == []

        intent = extract_intent("   ")
        assert intent.operation is None
        assert intent.operands == []

    def test_case_insensitive_matching(self):
        """Operation detection should be case-insensitive."""
        intent = extract_intent("SUM PAID")
        assert intent.operation == "aggregate"
        assert intent.operands == ["PAID"]

    def test_operand_preserves_original_case(self):
        """Extracted operands should preserve original casing from the question."""
        intent = extract_intent("Sum paid")
        assert intent.operands == ["paid"]

    def test_no_operand_after_keyword(self):
        """If keyword exists but no operand follows, operands list is empty."""
        intent = extract_intent("Sum")
        assert intent.operation == "aggregate"
        assert intent.operands == []

    def test_longer_keyword_matches_before_shorter(self):
        """'group by' should match before 'group' when both are present."""
        intent = extract_intent("Group by Course")
        assert intent.operation == "groupby"
        assert intent.operands == ["Course"]

    def test_multiple_operations_first_wins(self):
        """When multiple keywords exist, the first one in the question wins."""
        intent = extract_intent("Sum Paid and sort by Date")
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_filter_symbol_equals(self):
        """Symbol '=' should be detected as filter."""
        intent = extract_intent("Course = Math")
        assert intent.operation == "filter"
        assert intent.operands == ["Course"]

    def test_top_synonym_largest(self):
        """'largest' should map to top_n."""
        intent = extract_intent("Largest Paid")
        assert intent.operation == "top_n"
        assert intent.operands == ["Paid"]

    def test_top_synonym_smallest(self):
        """'smallest' should map to top_n."""
        intent = extract_intent("Smallest Paid")
        assert intent.operation == "top_n"
        assert intent.operands == ["Paid"]


# ---------------------------------------------------------------------------
# SchemaResolution / resolve_schema_references tests
# ---------------------------------------------------------------------------

class TestResolveSchemaReferences:
    """Tests for the deterministic schema resolution layer."""

    def test_pass_explicit_valid_references(self, sample_profile):
        """Explicit, valid column references must resolve successfully."""
        resolution = resolve_schema_references("Sum Paid", sample_profile)
        assert resolution.resolved is True
        assert resolution.missing_columns == []
        assert resolution.suggestions == {}

    def test_pass_group_by_valid(self, sample_profile):
        """Explicit group by with valid column must resolve."""
        resolution = resolve_schema_references("Group by Course", sample_profile)
        assert resolution.resolved is True
        assert resolution.missing_columns == []
        assert resolution.suggestions == {}

    def test_pass_sort_by_valid(self, sample_profile):
        """Explicit sort by with valid column must resolve."""
        resolution = resolve_schema_references("Sort by Date", sample_profile)
        assert resolution.resolved is True
        assert resolution.missing_columns == []
        assert resolution.suggestions == {}

    def test_pass_top_n_valid(self, sample_profile):
        """Explicit top_n with valid column must resolve."""
        resolution = resolve_schema_references("Highest Paid", sample_profile)
        assert resolution.resolved is True
        assert resolution.missing_columns == []
        assert resolution.suggestions == {}

    def test_fail_explicit_invalid_reference(self, sample_profile):
        """Explicit, invalid column reference must fail resolution."""
        resolution = resolve_schema_references("Sum Salary", sample_profile)
        assert resolution.resolved is False
        assert "Salary" in resolution.missing_columns
        # Fuzzy suggestion should be present
        assert "Salary" in resolution.suggestions
        assert "Paid" in resolution.suggestions["Salary"]

    def test_fail_multiple_invalid_references(self, sample_profile):
        """Multiple invalid references must all be reported as missing."""
        resolution = resolve_schema_references("Sum Salary and Count Wage", sample_profile)
        assert resolution.resolved is False
        assert "Salary" in resolution.missing_columns
        assert "Wage" in resolution.missing_columns

    def test_fail_filter_invalid_column(self, sample_profile):
        """Filter with invalid column must fail resolution."""
        resolution = resolve_schema_references("Salary > 1000", sample_profile)
        assert resolution.resolved is False
        assert "Salary" in resolution.missing_columns

    def test_ignore_natural_language_no_operands(self, sample_profile):
        """Natural language questions must pass with empty operands."""
        resolution = resolve_schema_references(
            "Which course generated the highest revenue?", sample_profile
        )
        assert resolution.resolved is True
        assert resolution.missing_columns == []
        assert resolution.suggestions == {}

    def test_ignore_ambiguous_business_terms(self, sample_profile):
        """Questions with ambiguous business terms but no explicit operation pass."""
        resolution = resolve_schema_references(
            "How much money was collected from students?", sample_profile
        )
        assert resolution.resolved is True
        assert resolution.missing_columns == []

    def test_suggestions_empty_when_no_match(self, minimal_profile):
        """If no close match exists, suggestions must be empty."""
        resolution = resolve_schema_references("Sum Gamma", minimal_profile)
        assert resolution.resolved is False
        assert "Gamma" in resolution.missing_columns
        assert resolution.suggestions.get("Gamma") is None

    def test_suggestions_single_match(self, sample_profile):
        """A single close match should be returned as the top suggestion."""
        resolution = resolve_schema_references("Sum Salry", sample_profile)
        assert resolution.resolved is False
        assert resolution.suggestions.get("Salry") == ["Paid"]

    def test_partial_column_name_not_matched_as_operand(self, sample_profile):
        """Partial column names that are not exact schema keys should fail."""
        resolution = resolve_schema_references("Sum Pay", sample_profile)
        assert resolution.resolved is False
        assert "Pay" in resolution.missing_columns

    def test_empty_dataset_columns(self):
        """Empty dataset profile should cause any operand to be missing."""
        profile = {"shape": {"rows": 0, "columns": 0}, "columns": {}}
        resolution = resolve_schema_references("Sum Paid", profile)
        assert resolution.resolved is False
        assert "Paid" in resolution.missing_columns

    def test_case_sensitive_column_matching(self, sample_profile):
        """Column matching is case-sensitive against schema keys."""
        resolution = resolve_schema_references("Sum paid", sample_profile)
        assert resolution.resolved is False
        assert "paid" in resolution.missing_columns

    def test_valid_references_preserve_order(self, sample_profile):
        """Multiple valid operands should all be preserved."""
        resolution = resolve_schema_references(
            "Group by Course and Student", sample_profile
        )
        assert resolution.resolved is True
        assert resolution.missing_columns == []

    def test_suggestion_cutoff_prevents_weak_matches(self, minimal_profile):
        """Weak matches below the difflib cutoff should not appear in suggestions."""
        resolution = resolve_schema_references("Sum ZZZZZ", minimal_profile)
        assert resolution.resolved is False
        assert resolution.suggestions.get("ZZZZZ") is None


# ---------------------------------------------------------------------------
# Dataclass structure tests
# ---------------------------------------------------------------------------

class TestDataClasses:
    """Verify the dataclass contracts remain stable."""

    def test_intent_reference_defaults(self):
        """IntentReference should have safe defaults."""
        intent = IntentReference()
        assert intent.operation is None
        assert intent.operands == []

    def test_intent_reference_with_values(self):
        """IntentReference should store provided values."""
        intent = IntentReference(operation="aggregate", operands=["Paid"])
        assert intent.operation == "aggregate"
        assert intent.operands == ["Paid"]

    def test_schema_resolution_defaults(self):
        """SchemaResolution should default to resolved=True."""
        resolution = SchemaResolution()
        assert resolution.resolved is True
        assert resolution.missing_columns == []
        assert resolution.suggestions == {}

    def test_schema_resolution_with_values(self):
        """SchemaResolution should store provided values."""
        resolution = SchemaResolution(
            resolved=False,
            missing_columns=["Salary"],
            suggestions={"Salary": ["Paid"]},
        )
        assert resolution.resolved is False
        assert resolution.missing_columns == ["Salary"]
        assert resolution.suggestions == {"Salary": ["Paid"]}


# ---------------------------------------------------------------------------
# Keyword dictionary coverage tests
# ---------------------------------------------------------------------------

class TestKeywordDictionaries:
    """Ensure all expected keywords are present in the centralized dicts."""

    def test_aggregation_keywords(self):
        expected = {"sum", "total", "avg", "average", "mean", "count", "min", "maximum", "max", "minimum"}
        assert expected.issubset(set(AGGREGATIONS.keys()))

    def test_group_by_keywords(self):
        expected = {"group by", "group", "grouped by", "grouped", "per"}
        assert expected.issubset(set(GROUP_BY.keys()))

    def test_sort_keywords(self):
        expected = {"sort by", "order by", "sorted by", "ordered by", "sort", "order"}
        assert expected.issubset(set(SORT.keys()))

    def test_top_bottom_keywords(self):
        expected = {"top", "bottom", "highest", "lowest", "largest", "smallest"}
        assert expected.issubset(set(TOP_BOTTOM.keys()))

    def test_filter_keywords(self):
        expected = {"=", "equals", "equal", "is", ">", "greater than", "<", "less than", ">=", "<=", "contains"}
        assert expected.issubset(set(FILTER.keys()))
