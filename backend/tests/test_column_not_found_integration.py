"""Integration tests for ColumnNotFoundError handling in the API layer.

Run from the backend directory:
    python -m pytest tests/test_column_not_found_integration.py -v

Or without pytest:
    python tests/test_column_not_found_integration.py
"""

from __future__ import annotations

import sys
import os
import types
from unittest.mock import MagicMock

# Ensure backend is importable
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BACKEND_DIR))

# Mock heavy external dependencies before importing app modules
google_mod = types.ModuleType("google")
genai_mod = types.ModuleType("google.genai")
types_mod = types.ModuleType("google.genai.types")
errors_mod = types.ModuleType("google.genai.errors")

genai_mod.types = types_mod
genai_mod.errors = errors_mod
google_mod.genai = genai_mod

errors_mod.ClientError = Exception
errors_mod.ServerError = Exception
types_mod.GenerateContentConfig = MagicMock
types_mod.Part = MagicMock
types_mod.Content = MagicMock

sys.modules.setdefault("google", google_mod)
sys.modules.setdefault("google.genai", genai_mod)
sys.modules.setdefault("google.genai.types", types_mod)
sys.modules.setdefault("google.genai.errors", errors_mod)
sys.modules.setdefault("google.generativeai", MagicMock())

from fastapi.testclient import TestClient

from app.core.dependencies import (
    get_chart_builder,
    get_executor,
    get_explainer,
    get_planner,
    get_session_manager,
)
from app.core.exceptions import ColumnNotFoundError
from app.main import create_app


def _build_mock_session_manager():
    """Create a mock session manager with a valid session and dataset profile."""
    mock_manager = MagicMock()
    mock_manager.get_session.return_value = {"session_id": "test-session"}
    mock_manager.get_profile.return_value = {
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
        ],
    }
    return mock_manager


def _build_mock_planner(column: str | list[str] = "Salary"):
    """Create a mock planner that raises ColumnNotFoundError on plan()."""
    mock_planner = MagicMock()
    available = ["Paid", "Student", "Course", "Date", "Transaction"]
    details = {}
    if isinstance(column, str):
        details = {"did_you_mean": {column: ["Paid"]}}
    else:
        details = {"did_you_mean": {c: ["Paid"] for c in column}}
    mock_planner.plan.side_effect = ColumnNotFoundError(
        column=column,
        available_columns=available,
        details=details,
    )
    return mock_planner


def test_analyze_endpoint_returns_400_for_missing_column():
    """POST /api/analyze/ must return HTTP 400 with structured error when column is missing."""
    app = create_app()

    mock_session_manager = _build_mock_session_manager()
    mock_planner = _build_mock_planner("Salary")
    mock_executor = MagicMock()
    mock_chart_builder = MagicMock()
    mock_explainer = MagicMock()

    app.dependency_overrides[get_session_manager] = lambda: mock_session_manager
    app.dependency_overrides[get_planner] = lambda: mock_planner
    app.dependency_overrides[get_executor] = lambda: mock_executor
    app.dependency_overrides[get_chart_builder] = lambda: mock_chart_builder
    app.dependency_overrides[get_explainer] = lambda: mock_explainer

    client = TestClient(app)

    response = client.post(
        "/api/analyze/",
        json={
            "session_id": "test-session",
            "question": "Sum Salary",
        },
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"

    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "COLUMN_NOT_FOUND"
    assert "Salary" in body["error"]["message"]
    assert body["error"]["details"]["column"] == "Salary"
    assert "did_you_mean" in body["error"]["details"]
    assert body["error"]["details"]["did_you_mean"]["Salary"] == ["Paid"]


def test_analyze_endpoint_returns_400_for_multiple_missing_columns():
    """POST /api/analyze/ must return HTTP 400 with all missing columns listed."""
    app = create_app()

    mock_session_manager = _build_mock_session_manager()
    mock_planner = _build_mock_planner(["Salary", "Wage"])
    mock_executor = MagicMock()
    mock_chart_builder = MagicMock()
    mock_explainer = MagicMock()

    app.dependency_overrides[get_session_manager] = lambda: mock_session_manager
    app.dependency_overrides[get_planner] = lambda: mock_planner
    app.dependency_overrides[get_executor] = lambda: mock_executor
    app.dependency_overrides[get_chart_builder] = lambda: mock_chart_builder
    app.dependency_overrides[get_explainer] = lambda: mock_explainer

    client = TestClient(app)

    response = client.post(
        "/api/analyze/",
        json={
            "session_id": "test-session",
            "question": "Sum Salary and Wage",
        },
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"

    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "COLUMN_NOT_FOUND"
    assert "Salary" in body["error"]["message"]
    assert "Wage" in body["error"]["message"]
    assert isinstance(body["error"]["details"]["column"], list)
    assert "Salary" in body["error"]["details"]["column"]
    assert "Wage" in body["error"]["details"]["column"]


def test_stream_endpoint_returns_error_event_for_missing_column():
    """POST /api/stream/ must emit an error SSE event when column is missing."""
    app = create_app()

    mock_session_manager = _build_mock_session_manager()
    mock_planner = _build_mock_planner("Salary")
    mock_executor = MagicMock()
    mock_chart_builder = MagicMock()
    mock_explainer = MagicMock()
    mock_llm_client = MagicMock()

    from app.core.dependencies import get_llm_client
    app.dependency_overrides[get_session_manager] = lambda: mock_session_manager
    app.dependency_overrides[get_planner] = lambda: mock_planner
    app.dependency_overrides[get_executor] = lambda: mock_executor
    app.dependency_overrides[get_chart_builder] = lambda: mock_chart_builder
    app.dependency_overrides[get_explainer] = lambda: mock_explainer
    app.dependency_overrides[get_llm_client] = lambda: mock_llm_client

    client = TestClient(app)

    with client.stream("POST", "/api/stream/", json={
        "session_id": "test-session",
        "question": "Sum Salary",
    }) as response:
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        events = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(line.replace("data: ", "").strip())
        
        error_events = [e for e in events if '"error_code"' in e and '"COLUMN_NOT_FOUND"' in e]
        assert len(error_events) >= 1, f"Expected error event, got events: {events}"
        
        import json
        error_payload = json.loads(error_events[0])
        assert error_payload["error_code"] == "COLUMN_NOT_FOUND"
        assert "Salary" in error_payload["message"]
        assert error_payload["details"]["column"] == "Salary"
        assert error_payload["details"]["did_you_mean"]["Salary"] == ["Paid"]


if __name__ == "__main__":
    import traceback

    passed = 0
    failed = 0

    tests = [
        test_analyze_endpoint_returns_400_for_missing_column,
        test_analyze_endpoint_returns_400_for_multiple_missing_columns,
        test_stream_endpoint_returns_error_event_for_missing_column,
    ]

    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL: {test.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed}/{len(tests)} tests passed.")
    sys.exit(0 if failed == 0 else 1)
