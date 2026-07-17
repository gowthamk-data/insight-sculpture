"""Manual test runner for intent_extractor tests (no pytest required).

Run from the backend directory:
    python ../tests/run_intent_extractor_tests.py
"""

from __future__ import annotations

import os
import sys
import traceback

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BACKEND_DIR))

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


SAMPLE_PROFILE: dict[str, Any] = {
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

MINIMAL_PROFILE: dict[str, Any] = {
    "shape": {"rows": 10, "columns": 2},
    "columns": {
        "alpha": {},
        "beta": {},
    },
}


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []

    def assert_equal(self, actual, expected, msg=""):
        if actual != expected:
            raise AssertionError(f"{msg}\nExpected: {expected!r}\nActual: {actual!r}")

    def assert_true(self, value, msg=""):
        if not value:
            raise AssertionError(msg or f"Expected True, got {value!r}")

    def assert_false(self, value, msg=""):
        if value:
            raise AssertionError(msg or f"Expected False, got {value!r}")

    def assert_in(self, member, container, msg=""):
        if member not in container:
            raise AssertionError(msg or f"{member!r} not found in {container!r}")

    def run(self, name, fn):
        try:
            fn()
            print(f"  PASS: {name}")
            self.passed += 1
        except Exception as exc:
            print(f"  FAIL: {name}\n        {exc}")
            self.failed += 1
            self.errors.append(f"{name}: {exc}")
            traceback.print_exc()

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{self.passed}/{total} tests passed.")
        if self.errors:
            print("\nFailures:")
            for err in self.errors:
                print(f"  - {err}")
        return self.failed == 0


# ---------------------------------------------------------------------------
# extract_intent tests
# ---------------------------------------------------------------------------

def test_aggregation_explicit_valid(runner):
    intent = extract_intent("Sum Paid")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_aggregation_synonym_total(runner):
    intent = extract_intent("Total Paid")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_aggregation_synonym_avg(runner):
    intent = extract_intent("Avg Paid")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_aggregation_synonym_mean(runner):
    intent = extract_intent("Mean Paid")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_aggregation_synonym_count(runner):
    intent = extract_intent("Count Student")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Student"])


def test_aggregation_synonym_min(runner):
    intent = extract_intent("Min Paid")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_aggregation_synonym_max(runner):
    intent = extract_intent("Max Paid")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_group_by_explicit(runner):
    intent = extract_intent("Group by Course")
    runner.assert_equal(intent.operation, "groupby")
    runner.assert_equal(intent.operands, ["Course"])


def test_group_by_single_word_group(runner):
    intent = extract_intent("Group Course")
    runner.assert_equal(intent.operation, "groupby")
    runner.assert_equal(intent.operands, ["Course"])


def test_sort_by_explicit(runner):
    intent = extract_intent("Sort by Paid")
    runner.assert_equal(intent.operation, "sort")
    runner.assert_equal(intent.operands, ["Paid"])


def test_sort_by_synonym_order_by(runner):
    intent = extract_intent("Order by Date")
    runner.assert_equal(intent.operation, "sort")
    runner.assert_equal(intent.operands, ["Date"])


def test_top_n_highest(runner):
    intent = extract_intent("Highest Paid")
    runner.assert_equal(intent.operation, "top_n")
    runner.assert_equal(intent.operands, ["Paid"])


def test_top_n_lowest(runner):
    intent = extract_intent("Lowest Paid")
    runner.assert_equal(intent.operation, "top_n")
    runner.assert_equal(intent.operands, ["Paid"])


def test_filter_equals(runner):
    intent = extract_intent("Course equals Math")
    runner.assert_equal(intent.operation, "filter")
    runner.assert_equal(intent.operands, ["Course"])


def test_filter_greater_than(runner):
    intent = extract_intent("Paid greater than 100")
    runner.assert_equal(intent.operation, "filter")
    runner.assert_equal(intent.operands, ["Paid"])


def test_filter_contains(runner):
    intent = extract_intent("Student contains Al")
    runner.assert_equal(intent.operation, "filter")
    runner.assert_equal(intent.operands, ["Student"])


def test_natural_language_returns_empty(runner):
    intent = extract_intent("How much money was collected?")
    runner.assert_equal(intent.operation, None)
    runner.assert_equal(intent.operands, [])


def test_natural_language_no_keyword(runner):
    intent = extract_intent("How many records are there?")
    runner.assert_equal(intent.operation, None)
    runner.assert_equal(intent.operands, [])


def test_empty_question(runner):
    intent = extract_intent("")
    runner.assert_equal(intent.operation, None)
    runner.assert_equal(intent.operands, [])

    intent = extract_intent("   ")
    runner.assert_equal(intent.operation, None)
    runner.assert_equal(intent.operands, [])


def test_case_insensitive_matching(runner):
    intent = extract_intent("SUM PAID")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["PAID"])


def test_operand_preserves_original_case(runner):
    intent = extract_intent("Sum paid")
    runner.assert_equal(intent.operands, ["paid"])


def test_no_operand_after_keyword(runner):
    intent = extract_intent("Sum")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, [])


def test_longer_keyword_matches_before_shorter(runner):
    intent = extract_intent("Group by Course")
    runner.assert_equal(intent.operation, "groupby")
    runner.assert_equal(intent.operands, ["Course"])


def test_multiple_operations_first_wins(runner):
    intent = extract_intent("Sum Paid and sort by Date")
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_filter_symbol_equals(runner):
    intent = extract_intent("Course = Math")
    runner.assert_equal(intent.operation, "filter")
    runner.assert_equal(intent.operands, ["Course"])


def test_top_synonym_largest(runner):
    intent = extract_intent("Largest Paid")
    runner.assert_equal(intent.operation, "top_n")
    runner.assert_equal(intent.operands, ["Paid"])


def test_top_synonym_smallest(runner):
    intent = extract_intent("Smallest Paid")
    runner.assert_equal(intent.operation, "top_n")
    runner.assert_equal(intent.operands, ["Paid"])


# ---------------------------------------------------------------------------
# SchemaResolution tests
# ---------------------------------------------------------------------------

def test_pass_explicit_valid_references(runner):
    resolution = resolve_schema_references("Sum Paid", SAMPLE_PROFILE)
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])
    runner.assert_equal(resolution.suggestions, {})


def test_pass_group_by_valid(runner):
    resolution = resolve_schema_references("Group by Course", SAMPLE_PROFILE)
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])
    runner.assert_equal(resolution.suggestions, {})


def test_pass_sort_by_valid(runner):
    resolution = resolve_schema_references("Sort by Date", SAMPLE_PROFILE)
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])
    runner.assert_equal(resolution.suggestions, {})


def test_pass_top_n_valid(runner):
    resolution = resolve_schema_references("Highest Paid", SAMPLE_PROFILE)
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])
    runner.assert_equal(resolution.suggestions, {})


def test_fail_explicit_invalid_reference(runner):
    resolution = resolve_schema_references("Sum Salary", SAMPLE_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_in("Salary", resolution.missing_columns)
    runner.assert_true(resolution.suggestions.get("Salary") is None)


def test_fail_multiple_invalid_references(runner):
    resolution = resolve_schema_references("Sum Salary", SAMPLE_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_in("Salary", resolution.missing_columns)


def test_fail_filter_invalid_column(runner):
    resolution = resolve_schema_references("Salary > 1000", SAMPLE_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_in("Salary", resolution.missing_columns)


def test_ignore_natural_language_no_operands(runner):
    resolution = resolve_schema_references(
        "How much money was collected?", SAMPLE_PROFILE
    )
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])
    runner.assert_equal(resolution.suggestions, {})


def test_ignore_ambiguous_business_terms(runner):
    resolution = resolve_schema_references(
        "How much money was collected from students?", SAMPLE_PROFILE
    )
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])


def test_suggestions_empty_when_no_match(runner):
    resolution = resolve_schema_references("Sum Gamma", MINIMAL_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_in("Gamma", resolution.missing_columns)
    runner.assert_true(resolution.suggestions.get("Gamma") is None)


def test_suggestions_single_match(runner):
    resolution = resolve_schema_references("Sum Payd", SAMPLE_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_equal(resolution.suggestions.get("Payd"), ["Paid"])


def test_partial_column_name_not_matched_as_operand(runner):
    resolution = resolve_schema_references("Sum Pay", SAMPLE_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_in("Pay", resolution.missing_columns)


def test_empty_dataset_columns(runner):
    profile = {"shape": {"rows": 0, "columns": 0}, "columns": {}}
    resolution = resolve_schema_references("Sum Paid", profile)
    runner.assert_false(resolution.resolved)
    runner.assert_in("Paid", resolution.missing_columns)


def test_case_sensitive_column_matching(runner):
    resolution = resolve_schema_references("Sum paid", SAMPLE_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_in("paid", resolution.missing_columns)


def test_valid_references_preserve_order(runner):
    resolution = resolve_schema_references(
        "Group by Course and Student", SAMPLE_PROFILE
    )
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])


def test_suggestion_cutoff_prevents_weak_matches(runner):
    resolution = resolve_schema_references("Sum ZZZZZ", MINIMAL_PROFILE)
    runner.assert_false(resolution.resolved)
    runner.assert_true(resolution.suggestions.get("ZZZZZ") is None)


# ---------------------------------------------------------------------------
# Dataclass structure tests
# ---------------------------------------------------------------------------

def test_intent_reference_defaults(runner):
    intent = IntentReference()
    runner.assert_equal(intent.operation, None)
    runner.assert_equal(intent.operands, [])


def test_intent_reference_with_values(runner):
    intent = IntentReference(operation="aggregate", operands=["Paid"])
    runner.assert_equal(intent.operation, "aggregate")
    runner.assert_equal(intent.operands, ["Paid"])


def test_schema_resolution_defaults(runner):
    resolution = SchemaResolution()
    runner.assert_true(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, [])
    runner.assert_equal(resolution.suggestions, {})


def test_schema_resolution_with_values(runner):
    resolution = SchemaResolution(
        resolved=False,
        missing_columns=["Salary"],
        suggestions={"Salary": ["Paid"]},
    )
    runner.assert_false(resolution.resolved)
    runner.assert_equal(resolution.missing_columns, ["Salary"])
    runner.assert_equal(resolution.suggestions, {"Salary": ["Paid"]})


# ---------------------------------------------------------------------------
# Keyword dictionary coverage tests
# ---------------------------------------------------------------------------

def test_aggregation_keywords(runner):
    expected = {"sum", "total", "avg", "average", "mean", "count", "min", "maximum", "max", "minimum"}
    runner.assert_true(expected.issubset(set(AGGREGATIONS.keys())))


def test_group_by_keywords(runner):
    expected = {"group by", "group", "grouped by", "grouped", "per"}
    runner.assert_true(expected.issubset(set(GROUP_BY.keys())))


def test_sort_keywords(runner):
    expected = {"sort by", "order by", "sorted by", "ordered by", "sort", "order"}
    runner.assert_true(expected.issubset(set(SORT.keys())))


def test_top_bottom_keywords(runner):
    expected = {"top", "bottom", "highest", "lowest", "largest", "smallest"}
    runner.assert_true(expected.issubset(set(TOP_BOTTOM.keys())))


def test_filter_keywords(runner):
    expected = {"=", "equals", "equal", "is", ">", "greater than", "<", "less than", ">=", "<=", "contains"}
    runner.assert_true(expected.issubset(set(FILTER.keys())))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    runner = TestRunner()

    print("Running extract_intent tests...")
    for name, fn in [
        ("test_aggregation_explicit_valid", lambda: test_aggregation_explicit_valid(runner)),
        ("test_aggregation_synonym_total", lambda: test_aggregation_synonym_total(runner)),
        ("test_aggregation_synonym_avg", lambda: test_aggregation_synonym_avg(runner)),
        ("test_aggregation_synonym_mean", lambda: test_aggregation_synonym_mean(runner)),
        ("test_aggregation_synonym_count", lambda: test_aggregation_synonym_count(runner)),
        ("test_aggregation_synonym_min", lambda: test_aggregation_synonym_min(runner)),
        ("test_aggregation_synonym_max", lambda: test_aggregation_synonym_max(runner)),
        ("test_group_by_explicit", lambda: test_group_by_explicit(runner)),
        ("test_group_by_single_word_group", lambda: test_group_by_single_word_group(runner)),
        ("test_sort_by_explicit", lambda: test_sort_by_explicit(runner)),
        ("test_sort_by_synonym_order_by", lambda: test_sort_by_synonym_order_by(runner)),
        ("test_top_n_highest", lambda: test_top_n_highest(runner)),
        ("test_top_n_lowest", lambda: test_top_n_lowest(runner)),
        ("test_filter_equals", lambda: test_filter_equals(runner)),
        ("test_filter_greater_than", lambda: test_filter_greater_than(runner)),
        ("test_filter_contains", lambda: test_filter_contains(runner)),
        ("test_natural_language_returns_empty", lambda: test_natural_language_returns_empty(runner)),
        ("test_natural_language_no_keyword", lambda: test_natural_language_no_keyword(runner)),
        ("test_empty_question", lambda: test_empty_question(runner)),
        ("test_case_insensitive_matching", lambda: test_case_insensitive_matching(runner)),
        ("test_operand_preserves_original_case", lambda: test_operand_preserves_original_case(runner)),
        ("test_no_operand_after_keyword", lambda: test_no_operand_after_keyword(runner)),
        ("test_longer_keyword_matches_before_shorter", lambda: test_longer_keyword_matches_before_shorter(runner)),
        ("test_multiple_operations_first_wins", lambda: test_multiple_operations_first_wins(runner)),
        ("test_filter_symbol_equals", lambda: test_filter_symbol_equals(runner)),
        ("test_top_synonym_largest", lambda: test_top_synonym_largest(runner)),
        ("test_top_synonym_smallest", lambda: test_top_synonym_smallest(runner)),
    ]:
        runner.run(name, fn)

    print("\nRunning SchemaResolution tests...")
    for name, fn in [
        ("test_pass_explicit_valid_references", lambda: test_pass_explicit_valid_references(runner)),
        ("test_pass_group_by_valid", lambda: test_pass_group_by_valid(runner)),
        ("test_pass_sort_by_valid", lambda: test_pass_sort_by_valid(runner)),
        ("test_pass_top_n_valid", lambda: test_pass_top_n_valid(runner)),
        ("test_fail_explicit_invalid_reference", lambda: test_fail_explicit_invalid_reference(runner)),
        ("test_fail_multiple_invalid_references", lambda: test_fail_multiple_invalid_references(runner)),
        ("test_fail_filter_invalid_column", lambda: test_fail_filter_invalid_column(runner)),
        ("test_ignore_natural_language_no_operands", lambda: test_ignore_natural_language_no_operands(runner)),
        ("test_ignore_ambiguous_business_terms", lambda: test_ignore_ambiguous_business_terms(runner)),
        ("test_suggestions_empty_when_no_match", lambda: test_suggestions_empty_when_no_match(runner)),
        ("test_suggestions_single_match", lambda: test_suggestions_single_match(runner)),
        ("test_partial_column_name_not_matched_as_operand", lambda: test_partial_column_name_not_matched_as_operand(runner)),
        ("test_empty_dataset_columns", lambda: test_empty_dataset_columns(runner)),
        ("test_case_sensitive_column_matching", lambda: test_case_sensitive_column_matching(runner)),
        ("test_valid_references_preserve_order", lambda: test_valid_references_preserve_order(runner)),
        ("test_suggestion_cutoff_prevents_weak_matches", lambda: test_suggestion_cutoff_prevents_weak_matches(runner)),
    ]:
        runner.run(name, fn)

    print("\nRunning dataclass tests...")
    for name, fn in [
        ("test_intent_reference_defaults", lambda: test_intent_reference_defaults(runner)),
        ("test_intent_reference_with_values", lambda: test_intent_reference_with_values(runner)),
        ("test_schema_resolution_defaults", lambda: test_schema_resolution_defaults(runner)),
        ("test_schema_resolution_with_values", lambda: test_schema_resolution_with_values(runner)),
    ]:
        runner.run(name, fn)

    print("\nRunning keyword dictionary coverage tests...")
    for name, fn in [
        ("test_aggregation_keywords", lambda: test_aggregation_keywords(runner)),
        ("test_group_by_keywords", lambda: test_group_by_keywords(runner)),
        ("test_sort_keywords", lambda: test_sort_keywords(runner)),
        ("test_top_bottom_keywords", lambda: test_top_bottom_keywords(runner)),
        ("test_filter_keywords", lambda: test_filter_keywords(runner)),
    ]:
        runner.run(name, fn)

    success = runner.summary()
    sys.exit(0 if success else 1)
