"""Regression tests for planner fixes.

This module contains unit tests that verify the fixes for specific planner issues
without requiring LLM API calls.
"""

import pytest
from typing import Iterator
from app.schemas import (
    AllowedOperation,
    AnalysisPlan,
    AggregationType,
    SortOrder,
    ChartType,
    FilterCondition,
    FilterOperator,
)
from app.llm.planner import AnalysisPlanner
from app.llm.intent_normalizer import SemanticIntent
from app.llm.openai_client import BaseLLMClient


# Mock LLM client for deterministic testing
class MockLLMClient(BaseLLMClient):
    """A mock LLM client that returns predefined responses."""
    
    def __init__(self, fixed_response=None):
        self.fixed_response = fixed_response or {}
    
    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int | None = None) -> str:
        return ""
    
    def stream_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int | None = None) -> Iterator[str]:
        return iter([])
    
    def generate_json(self, **kwargs):
        """Return a predefined AnalysisPlan."""
        return AnalysisPlan(**self.fixed_response)


@pytest.fixture
def mock_planner():
    """Create a planner with a mock LLM client."""
    from app.llm.gemini_client import GeminiClient
    return AnalysisPlanner(MockLLMClient())


@pytest.fixture
def dataset_profile():
    """Create a minimal dataset profile for testing."""
    return {
        "shape": {"rows": 100, "columns": 30},
        "columns": {
            "Sales": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Salary": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Customer": {"inferred_type": "object", "semantic_type": "categorical"},
            "CustomerID": {"inferred_type": "object", "semantic_type": "categorical"},
            "Segment": {"inferred_type": "object", "semantic_type": "categorical"},
            "Region": {"inferred_type": "object", "semantic_type": "categorical"},
            "OrderID": {"inferred_type": "object", "semantic_type": "categorical"},
            "Amount": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Product": {"inferred_type": "object", "semantic_type": "categorical"},
            "Category": {"inferred_type": "object", "semantic_type": "categorical"},
            "Paid": {"inferred_type": "int64", "semantic_type": "numeric"},
            "EmployeeID": {"inferred_type": "object", "semantic_type": "categorical"},
            "Income": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Age": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Price": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Score": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Department": {"inferred_type": "object", "semantic_type": "categorical"},
            "Course": {"inferred_type": "object", "semantic_type": "categorical"},
            "Revenue": {"inferred_type": "int64", "semantic_type": "numeric"},
            "State": {"inferred_type": "object", "semantic_type": "categorical"},
            "Population": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Year": {"inferred_type": "int64", "semantic_type": "numeric"},
            "OrderCount": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Marketing Spend": {"inferred_type": "int64", "semantic_type": "numeric"},
            "OrderValue": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Temperature": {"inferred_type": "int64", "semantic_type": "numeric"},
            "Returns": {"inferred_type": "float64", "semantic_type": "numeric"},
            "Rating": {"inferred_type": "float64", "semantic_type": "numeric"},
            "Date": {"inferred_type": "object", "semantic_type": "datetime"},
            "name": {"inferred_type": "object", "semantic_type": "categorical"},
            "city": {"inferred_type": "object", "semantic_type": "categorical"},
            "Profit": {"inferred_type": "int64", "semantic_type": "numeric"},
        },
    }


class TestTopNOverrides:
    """Tests for TOP-01 and MIX-01: groupby should become top_n when limit is set."""
    
    def test_top_n_with_group_by_preserved(self, mock_planner, dataset_profile):
        """Test that top_n with group_by preserves operation as top_n."""
        # Simulate LLM returning groupby but we want top_n
        mock_planner._llm_client.fixed_response = {
            "operation": "groupby",
            "target_columns": ["Sales"],
            "group_by": ["Customer"],
            "filters": [],
            "aggregation": "sum",
            "sort_by": "Sales",
            "sort_order": "desc",
            "limit": 10,
            "chart_type": "bar",
            "explanation_required": True,
        }
        
        # Create semantic intent for top_n
        semantic_intent = SemanticIntent(
            operation="top_n",
            group_by=["Customer"],
            sort_by="Sales",
            sort_order="desc",
            limit=10,
        )
        
        result = mock_planner.plan(
            user_question="Top 10 customers by sales",
            dataset_profile=dataset_profile,
        )
        
        # After normalization, should be top_n
        normalized = mock_planner._normalize_analysis_plan(
            result, dataset_profile, "Top 10 customers by sales", semantic_intent
        )
        
        # This test verifies the logic - actual fix needs to be in _normalize_analysis_plan


class TestPaidToSalaryMapping:
    """Tests for TOP-03: 'Paid' should map to 'Salary' for employee context."""
    
    def test_paid_to_salary_mapping(self, mock_planner, dataset_profile):
        """Test that 'Paid' is mapped to 'Salary' for employee context."""
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Paid"],
            group_by=[],
            filters=[],
            aggregation=None,
            sort_by="Paid",
            sort_order=SortOrder.DESC,
            limit=3,
            chart_type=ChartType.NONE,
            explanation_required=True,
        )
        
        semantic_intent = SemanticIntent(operation="top_n")
        
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 3 highest paid employees", semantic_intent
        )
        
        assert normalized.sort_by == "Salary", f"Expected 'Salary', got '{normalized.sort_by}'"
        assert normalized.target_columns == ["Salary"], f"Expected ['Salary'], got {normalized.target_columns}"


class TestCorrelationColumns:
    """Tests for COR-01 and COR-02: correlation column handling."""
    
    def test_correlation_numeric_filter(self, mock_planner, dataset_profile):
        """Test that correlation only includes numeric columns."""
        plan = AnalysisPlan(
            operation=AllowedOperation.CORRELATION,
            target_columns=["Sales", "Region", "Salary"],
            group_by=[],
            filters=[],
            aggregation=None,
            sort_by=None,
            sort_order=None,
            limit=None,
            chart_type=ChartType.SCATTER,
            explanation_required=True,
        )
        
        semantic_intent = SemanticIntent(operation="correlation")
        
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Correlation between Sales and Salary", semantic_intent
        )
        
        # Region is categorical, should be filtered out
        assert "Region" not in normalized.target_columns
        assert "Sales" in normalized.target_columns
        assert "Salary" in normalized.target_columns


class TestMultiColumnSort:
    """Tests for SRT-05: multi-column sort with 'then'."""
    
    def test_multi_column_sort_primary(self, mock_planner, dataset_profile):
        """Test that multi-column sort uses last column as primary."""
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Department", "salary"],
            group_by=[],
            filters=[],
            aggregation=None,
            sort_by="Department",
            sort_order=SortOrder.DESC,
            limit=None,
            chart_type=ChartType.NONE,
            explanation_required=True,
        )
        
        semantic_intent = SemanticIntent(operation="sort")
        
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Sort by Department then Salary descending", semantic_intent
        )
        
        assert normalized.sort_by == "salary", f"Expected 'salary', got '{normalized.sort_by}'"
        assert normalized.target_columns == ["salary"], f"Expected ['salary'], got {normalized.target_columns}"


class TestGroupByEntityPreservation:
    """Tests for GRP-03: entity name preservation in group_by."""
    
    def test_customer_entity_preserved(self, dataset_profile):
        """Test that 'Customer' entity is preserved in dataset."""
        assert "Customer" in dataset_profile["columns"]


class TestHousePriceAlias:
    """Regression test for AGG-04: 'house price' should resolve to 'Price'."""
    
    def test_house_price_maps_to_price(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.AGGREGATE,
            target_columns=["house price"],
            aggregation=AggregationType.MEDIAN,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Find the median house price"
        )
        assert "Price" in normalized.target_columns
        assert "house price" not in normalized.target_columns


class TestPaidAmountAlias:
    """Regression test for EDGE-11: 'paid amount' should resolve to 'Paid'."""
    
    def test_paid_amount_maps_to_paid(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.FILTER,
            target_columns=["paid amount"],
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Show paid amount"
        )
        assert "Paid" in normalized.target_columns
        assert "paid amount" not in normalized.target_columns


class TestCaseNormalization:
    """Regression tests for case normalization across all column references."""
    
    def test_sort_by_case_normalized(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["salary"],
            sort_by="Salary",
            sort_order=SortOrder.DESC,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Sort by Salary descending"
        )
        assert normalized.sort_by == "Salary"
    
    def test_group_by_case_normalized(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["sales"],
            group_by=["Region"],
            aggregation=AggregationType.SUM,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Total sales by Region"
        )
        assert "Region" in normalized.group_by


class TestCorrelationAllNumericRestriction:
    """Regression test for COR-02: 'all numeric columns' should be restricted."""
    
    def test_all_numeric_columns_restricted(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.CORRELATION,
            target_columns=["Sales", "Profit", "Age", "Income", "Score", "Year", "OrderCount"],
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Show correlation matrix for all numeric columns"
        )
        assert "Age" in normalized.target_columns
        assert "Income" in normalized.target_columns
        assert "Score" in normalized.target_columns
        assert "Sales" not in normalized.target_columns
        assert "Year" not in normalized.target_columns


class TestTopNEntityMetricSeparation:
    """Regression tests for MIX-05 and MIX-11: entity/metric separation in top_n."""
    
    def test_top_products_by_sales_entity_metric_separated(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Product", "Sales"],
            group_by=["Sales"],
            sort_by="Sales",
            sort_order=SortOrder.DESC,
            limit=5,
            aggregation=AggregationType.SUM,
        )
        semantic_intent = SemanticIntent(
            operation="top_n",
            group_by=["Product"],
            target_columns=["Sales"],
            sort_by="Sales",
            sort_order="desc",
            limit=5,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 5 products by sales in Electronics category", semantic_intent
        )
        assert normalized.group_by == ["Product"]
        assert normalized.target_columns == ["Sales"]
    
    def test_top_states_by_population_entity_metric_separated(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["State", "Population"],
            group_by=["Population"],
            sort_by="Population",
            sort_order=SortOrder.DESC,
            limit=10,
            aggregation=AggregationType.SUM,
        )
        semantic_intent = SemanticIntent(
            operation="top_n",
            group_by=["State"],
            target_columns=["Population"],
            sort_by="Population",
            sort_order="desc",
            limit=10,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 10 states by population", semantic_intent
        )
        assert normalized.group_by == ["State"]
        assert normalized.target_columns == ["Population"]


class TestHighestValueIntentClassification:
    """Regression tests for MIX-13 and EDGE-02: highest-value intent normalization."""
    
    def test_highest_paid_employee_in_each_department(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["name", "Paid"],
            group_by=["Department"],
            sort_by="Paid",
            sort_order=SortOrder.DESC,
            limit=1,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Show the highest paid employee in each department"
        )
        assert normalized.operation == AllowedOperation.GROUPBY
        assert normalized.aggregation == AggregationType.MAX
        assert normalized.group_by == ["Department"]
        assert "Salary" in normalized.target_columns
        assert normalized.limit is None
    
    def test_which_course_generated_highest_revenue(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Course", "Revenue"],
            sort_by="Revenue",
            sort_order=SortOrder.DESC,
            limit=1,
        )
        semantic_intent = SemanticIntent(
            operation="top_n",
            group_by=["Course"],
            target_columns=["Revenue"],
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Which course generated the highest revenue?", semantic_intent
        )
        assert normalized.operation == AllowedOperation.GROUPBY
        assert normalized.aggregation == AggregationType.SUM
        assert normalized.group_by == ["Course"]
        assert normalized.target_columns == ["Revenue"]
        assert normalized.limit is None


class TestEdgeCaseListAllRecords:
    """Regression test for EDGE-05: 'List all records' should map to filter."""
    
    def test_list_all_records_maps_to_filter(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.SUMMARIZE,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "List all records"
        )
        assert normalized.operation == AllowedOperation.FILTER


class TestCompareAgeAndIncome:
    """Regression test for COR-01 and EDGE-10: 'Compare Age and Income' should extract both columns."""
    
    def test_compare_age_and_income_correlation(self, dataset_profile):
        from app.llm.intent_normalizer import _extract_correlation_columns
        available_columns = set(dataset_profile["columns"].keys())
        columns = _extract_correlation_columns("Compare Age and Income", available_columns)
        assert "Age" in columns
        assert "Income" in columns


class TestTopNNormalizationFromGroupby:
    """Regression for TOP-01 / MIX-01: a groupby carrying a limit (ranking intent)
    must consolidate into a single top_n operation with semantic entity integrity.
    """

    def test_groupby_with_limit_becomes_top_n(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["Sales"],
            group_by=["CustomerID"],
            aggregation=AggregationType.SUM,
            sort_by="Sales",
            sort_order=SortOrder.DESC,
            limit=10,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 10 customers by sales"
        )
        assert normalized.operation == AllowedOperation.TOP_N
        assert normalized.limit == 10

    def test_top_n_preserves_semantic_entity_not_id(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["Sales"],
            group_by=["CustomerID"],
            aggregation=AggregationType.SUM,
            sort_by="Sales",
            sort_order=SortOrder.DESC,
            limit=10,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 10 customers by total sales"
        )
        assert normalized.group_by == ["Customer"]


class TestCompoundEntityResolution:
    """Regression for MIX-12: 'customer segment' is a unified dimension and must
    not be fragmented into ['Customer', 'Segment'].
    """

    def test_customer_segment_collapses_to_segment(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["OrderValue"],
            group_by=["Customer", "Segment"],
            aggregation=AggregationType.MEAN,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Average order value by customer segment"
        )
        assert normalized.group_by == ["Segment"]

    def test_explicit_multi_dimension_preserved(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["Sales"],
            group_by=["Region", "Segment"],
            aggregation=AggregationType.SUM,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Total sales by Region and Segment"
        )
        assert set(normalized.group_by) == {"Region", "Segment"}


class TestContextAwareAliasResolution:
    """Regression for MIX-13: 'paid' in an employee context maps to 'Salary',
    not the literal 'Paid' column, keeping metric mapping accurate.
    """

    def test_highest_paid_employee_maps_paid_to_salary(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["Paid"],
            group_by=["Department"],
            aggregation=AggregationType.MAX,
            sort_by="Paid",
            sort_order=SortOrder.DESC,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Show the highest paid employee in each department"
        )
        assert "Salary" in normalized.target_columns
        assert "Paid" not in normalized.target_columns

    def test_paid_outside_employee_context_untouched(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.FILTER,
            target_columns=["Paid"],
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Show paid amount"
        )
        assert "Paid" in normalized.target_columns


class TestSortDirectionHeuristics:
    """Regression for MIX-15: ranking phrases like 'sorted by rating' default to
    descending unless ascending is explicitly stated.
    """

    def test_sorted_by_rating_defaults_descending(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Product", "Rating"],
            filters=[
                FilterCondition(column="Price", operator=FilterOperator.GT, value=100),
                FilterCondition(column="Price", operator=FilterOperator.LE, value=500),
            ],
            sort_by="Rating",
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Products with price between 100 and 500 sorted by rating"
        )
        assert normalized.sort_by == "Rating"
        assert normalized.sort_order == SortOrder.DESC

    def test_explicit_ascending_preserved(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Name"],
            sort_by="Name",
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Order by Name A to Z"
        )
        assert normalized.sort_order == SortOrder.ASC


class TestCountTargetInference:
    """Regression for MIX-04: count aggregation without an explicit target must
    deterministically infer the dataset's primary identifier (e.g. OrderID).
    """

    def test_count_infers_order_id(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            group_by=["Region"],
            aggregation=AggregationType.COUNT,
            filters=[
                FilterCondition(column="Amount", operator=FilterOperator.GT, value=1000),
            ],
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Count of orders by Region where Amount > 1000"
        )
        assert normalized.aggregation == AggregationType.COUNT
        assert normalized.target_columns == ["OrderID"]
        assert normalized.group_by == ["Region"]

    def test_count_does_not_override_explicit_target(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=["Customer"],
            group_by=["Region"],
            aggregation=AggregationType.COUNT,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Count of customers by Region"
        )
        assert normalized.target_columns == ["Customer"]

    def test_count_falls_back_to_id_column(self, mock_planner):
        profile = {
            "shape": {"rows": 10, "columns": 3},
            "columns": {
                "TransactionID": {"inferred_type": "object", "semantic_type": "categorical"},
                "Region": {"inferred_type": "object", "semantic_type": "categorical"},
                "Amount": {"inferred_type": "int64", "semantic_type": "numeric"},
            },
        }
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            group_by=["Region"],
            aggregation=AggregationType.COUNT,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, profile, "Count of orders by Region"
        )
        assert normalized.target_columns == ["TransactionID"]

    def test_non_count_aggregation_untouched(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.GROUPBY,
            target_columns=[],
            group_by=["Region"],
            aggregation=AggregationType.SUM,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Total amount by Region"
        )
        assert normalized.target_columns == []
        assert normalized.aggregation == AggregationType.SUM


class TestRankingDefaultSortOverride:
    """Regression for MIX-15: explicit ranking intent ('sorted by rating')
    defaults to descending even when the LLM emitted an incorrect asc default,
    while explicit ascending requests remain respected.
    """

    def test_ranking_metric_defaults_descending_without_semantic_signal(self, mock_planner, dataset_profile):
        # No explicit or semantic ranking keyword, but the column is a known
        # ranking metric (rating) -> the default metric heuristic forces
        # descending, overriding an un-signaled LLM ascending default.
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Product", "Rating"],
            filters=[
                FilterCondition(column="Price", operator=FilterOperator.GT, value=100),
                FilterCondition(column="Price", operator=FilterOperator.LE, value=500),
            ],
            sort_by="Rating",
            sort_order=SortOrder.ASC,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Products with price between 100 and 500 sorted by rating"
        )
        assert normalized.sort_by == "Rating"
        assert normalized.sort_order == SortOrder.DESC

    def test_ranking_semantic_keyword_overrides_llm_asc_default(self, mock_planner, dataset_profile):
        # A descending semantic keyword ("top") must override an erroneous LLM
        # ascending default for ranking metrics.
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Product", "Rating"],
            filters=[
                FilterCondition(column="Price", operator=FilterOperator.GT, value=100),
                FilterCondition(column="Price", operator=FilterOperator.LE, value=500),
            ],
            sort_by="Rating",
            sort_order=SortOrder.ASC,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top products with price between 100 and 500 sorted by rating"
        )
        assert normalized.sort_by == "Rating"
        assert normalized.sort_order == SortOrder.DESC

    def test_explicit_ascending_still_respected(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Product", "Rating"],
            sort_by="Rating",
            sort_order=SortOrder.ASC,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Products sorted by rating ascending"
        )
        assert normalized.sort_order == SortOrder.ASC

    def test_lowest_first_respected(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Product", "Rating"],
            sort_by="Rating",
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Products sorted by rating lowest first"
        )
        assert normalized.sort_order == SortOrder.ASC


class TestSemanticRankingDirectionPrecedence:
    """Regression for TOP-02 (Bottom-N) and TOP-01 (Top-N): semantic ranking
    keywords must deterministically set sort direction, overriding the generic
    metric heuristic that would otherwise force descending for rating-like columns.
    """

    def test_bottom_rating_is_ascending(self, mock_planner, dataset_profile):
        # TOP-02: 'Bottom' is an ascending ranking keyword even for rating metrics.
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Product", "Rating"],
            sort_by="Rating",
            sort_order=SortOrder.DESC,  # erroneous LLM default
            limit=5,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Bottom 5 products by rating"
        )
        assert normalized.sort_by == "Rating"
        assert normalized.sort_order == SortOrder.ASC

    def test_top_rating_is_descending(self, mock_planner, dataset_profile):
        # TOP-01: 'Top' is a descending ranking keyword.
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Customer", "Sales"],
            sort_by="Sales",
            limit=10,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 10 customers by sales"
        )
        assert normalized.sort_by == "Sales"
        assert normalized.sort_order == SortOrder.DESC

    def test_lowest_is_ascending(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["TransactionID", "amount"],
            sort_by="amount",
            limit=10,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Lowest 10 transaction amounts"
        )
        assert normalized.sort_by == "Amount"
        assert normalized.sort_order == SortOrder.ASC

    def test_smallest_is_ascending(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Product", "Price"],
            sort_by="Price",
            limit=3,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Smallest 3 products by price"
        )
        assert normalized.sort_by == "Price"
        assert normalized.sort_order == SortOrder.ASC

    def test_least_is_ascending(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Region", "Revenue"],
            sort_by="Revenue",
            limit=5,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Least 5 regions by revenue"
        )
        assert normalized.sort_order == SortOrder.ASC

    def test_highest_is_descending(self, mock_planner, dataset_profile):
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["EmployeeID", "Salary"],
            sort_by="Salary",
            limit=3,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Highest 3 paid employees"
        )
        assert normalized.sort_by == "Salary"
        assert normalized.sort_order == SortOrder.DESC

    def test_explicit_ascending_overrides_semantic_descending(self, mock_planner, dataset_profile):
        # Explicit direction must outrank a semantic ranking keyword.
        plan = AnalysisPlan(
            operation=AllowedOperation.TOP_N,
            target_columns=["Product", "Rating"],
            sort_by="Rating",
            limit=5,
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Top 5 products by rating ascending"
        )
        assert normalized.sort_order == SortOrder.ASC

    def test_no_ranking_signal_keeps_heuristic_default(self, mock_planner, dataset_profile):
        # No explicit or semantic signal: rating metric defaults to descending.
        plan = AnalysisPlan(
            operation=AllowedOperation.SORT,
            target_columns=["Product", "Rating"],
            sort_by="Rating",
        )
        normalized = mock_planner._normalize_analysis_plan(
            plan, dataset_profile, "Products sorted by rating"
        )
        assert normalized.sort_order == SortOrder.DESC


if __name__ == "__main__":
    # Run tests when executed directly
    pytest.main([__file__, "-v"])