"""Validation of the schema resolver fix — focuses on the real problem."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ["LLM_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = "test"
os.environ["OPENAI_API_KEY"] = "test"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "true"

from app.analytics.intent_extractor import is_plausible_column_candidate, _resolve_schema_references, extract_intent

# Test 1: is_plausible_column_candidate — stop words must be rejected
print("=" * 60)
print("TEST 1: is_plausible_column_candidate - stop words")
print("=" * 60)
tests = {
    "What": False, "ascending": False, "descending": False, "10": False,
    "the": False, "is": False, "show": False, "top": False, "bottom": False,
    "1000": False, "records": False, "data": False, "total": False,
    "sum": False, "count": False, "mean": False, "average": False,
    "min": False, "max": False, "size": False, "value": False,
    "Sales": True, "City": True, "Status": True, "Region": True,
    "age": True, "Salary": True, "Product": True, "Customer": True,
    "Profit": True, "Revenue": True, "OrderID": True, "CustomerID": True,
    "Grade": True, "Subject": True, "score": True, "rating": True,
}
all_pass = True
for token, expected in tests.items():
    result = is_plausible_column_candidate(token)
    status = "PASS" if result == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
        print(f"  {status}: is_plausible_column_candidate({token!r}) = {result}, expected {expected}")
if all_pass:
    print("  ALL PASSED")
print()

# Test 2: Real-world test — ColumnNotFoundError elimination
print("=" * 60)
print("TEST 2: ColumnNotFoundError elimination for English words")
print("=" * 60)

profile = {
    "columns": {
        "Sales": {"semantic_type": "numeric"},
        "Profit": {"semantic_type": "numeric"},
        "City": {"semantic_type": "categorical"},
        "Status": {"semantic_type": "categorical"},
        "age": {"semantic_type": "numeric"},
        "amount": {"semantic_type": "numeric"},
        "salary": {"semantic_type": "numeric"},
        "name": {"semantic_type": "categorical"},
        "Price": {"semantic_type": "numeric"},
        "Score": {"semantic_type": "numeric"},
        "Temperature": {"semantic_type": "numeric"},
        "Returns": {"semantic_type": "numeric"},
        "CustomerID": {"semantic_type": "categorical"},
        "OrderID": {"semantic_type": "categorical"},
        "Region": {"semantic_type": "categorical"},
        "Department": {"semantic_type": "categorical"},
        "Salary": {"semantic_type": "numeric"},
        "Category": {"semantic_type": "categorical"},
        "Product": {"semantic_type": "categorical"},
        "Date": {"semantic_type": "datetime"},
        "Revenue": {"semantic_type": "numeric"},
        "OrderCount": {"semantic_type": "numeric"},
        "Population": {"semantic_type": "numeric"},
        "State": {"semantic_type": "categorical"},
        "Segment": {"semantic_type": "categorical"},
        "OrderValue": {"semantic_type": "numeric"},
        "Rating": {"semantic_type": "numeric"},
        "Grade": {"semantic_type": "categorical"},
        "Subject": {"semantic_type": "categorical"},
        "Paid": {"semantic_type": "numeric"},
        "Course": {"semantic_type": "categorical"},
        "Amount": {"semantic_type": "numeric"},
        "Marketing Spend": {"semantic_type": "numeric"},
    }
}

# These queries should NEVER raise ColumnNotFoundError for English stop words.
# Previously they failed with "What", "ascending", "average", etc.
passing_queries = [
    "What is the total sales?",
    "What is the average salary?",
    "Show records where City = Chennai",
    "Sort by Date ascending",
    "Sort by Salary descending",
    "Show me everything",
    "List all records",
    "What is the average?",
    "Filter out nulls",
    "How many customers are there?",
    "What is the minimum score?",
    "What is the maximum profit?",
    "What is the mean temperature?",
    "What is the standard deviation of returns?",
    "Calculate the average salary",
    "What is the total sales?",
    "What is the mean temperature?",
]

all_pass = True
for q in passing_queries:
    res = _resolve_schema_references(q, profile)
    status = "PASS" if res.resolved else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {status}: {q!r:60s} resolved={res.resolved}")
    if not res.resolved:
        print(f"         missing={res.missing_columns}, suggestions={res.suggestions}")
if all_pass:
    print("  ALL PASSED - NO ColumnNotFoundError for English words!")
else:
    print("  NOTE: Remaining failures are cases where operands fuzzy-match real columns")
print()

# Test 3: Genuinely invalid columns still rejected
print("=" * 60)
print("TEST 3: Invalid columns still rejected")
print("=" * 60)
failing_queries = [
    "Sum NonExistentCol",        # NonExistentCol extracted as operand after "Sum"
    "Show InvalidCol = Chennai", # InvalidCol extracted as operand before "Filter"
]
for q in failing_queries:
    res = _resolve_schema_references(q, profile)
    status = "PASS" if not res.resolved else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {status}: {q!r:45s} resolved={res.resolved}, missing={res.missing_columns}")

print()

# Test 4: Misspellings still get suggestions
print("=" * 60)
print("TEST 4: Misspellings get suggestions")
print("=" * 60)
for q, expected_suggestion in [
    ("Sum Salry", "Salary"),
    ("Top 10 Produc", "Product"),
]:
    res = _resolve_schema_references(q, profile)
    has_suggestion = any(
        expected_suggestion in suggests
        for suggests in res.suggestions.values()
    )
    status = "PASS" if (not res.resolved and has_suggestion) else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {status}: {q!r:45s} resolved={res.resolved}, suggestions={res.suggestions}")

print()
print("=" * 60)
if all_pass:
    print("RESULT: ALL TESTS PASSED")
else:
    print("RESULT: SOME TESTS FAILED")
print("=" * 60)