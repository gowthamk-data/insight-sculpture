"""Deterministic schema resolution layer for the analytics pipeline.

This module acts as a pre-processor that intercepts explicit column references
in user questions and validates them against a dataset profile before the LLM
planner is invoked. It uses only rule-based parsing and centralized dictionaries;
no LLMs, NLP libraries, embeddings, or external APIs are used.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IntentReference:
    """Structured representation of an extracted intent from a user question.

    Attributes:
        operation: The detected analytics operation, or None if no explicit
            operation was found.
        operands: Column names syntactically attached to the detected operation.
            Empty when the question is purely natural language.
    """

    operation: str | None = None
    operands: list[str] = field(default_factory=list)


@dataclass
class SchemaResolution:
    """Result of validating extracted operands against a dataset profile.

    Attributes:
        resolved: True when all operands exist in the dataset schema.
        missing_columns: Column names that were not found in the schema.
        suggestions: Mapping of missing column names to close matches in the
            schema, generated via difflib.get_close_matches. Each value is a
            list of suggested column names ordered by similarity.
    """

    resolved: bool = True
    missing_columns: list[str] = field(default_factory=list)
    suggestions: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Centralized operation dictionaries
# ---------------------------------------------------------------------------

AGGREGATIONS: dict[str, str] = {
    "sum": "aggregate",
    "total": "aggregate",
    "avg": "aggregate",
    "average": "aggregate",
    "mean": "aggregate",
    "count": "aggregate",
    "min": "aggregate",
    "minimum": "aggregate",
    "max": "aggregate",
    "maximum": "aggregate",
}

GROUP_BY: dict[str, str] = {
    "group by": "groupby",
    "group": "groupby",
    "grouped by": "groupby",
    "grouped": "groupby",
    "per": "groupby",
}

SORT: dict[str, str] = {
    "sort by": "sort",
    "order by": "sort",
    "sorted by": "sort",
    "ordered by": "sort",
    "sort": "sort",
    "order": "sort",
}

FILTER: dict[str, str] = {
    "=": "filter",
    "equals": "filter",
    "equal": "filter",
    "is": "filter",
    ">": "filter",
    "greater than": "filter",
    "<": "filter",
    "less than": "filter",
    ">=": "filter",
    "<=": "filter",
    "contains": "filter",
}

TOP_BOTTOM: dict[str, str] = {
    "top": "top_n",
    "bottom": "top_n",
    "highest": "top_n",
    "lowest": "top_n",
    "largest": "top_n",
    "smallest": "top_n",
}

# Combined lookup for all operations (lower-cased keys)
_OPERATION_KEYWORDS: dict[str, str] = {
    **AGGREGATIONS,
    **GROUP_BY,
    **SORT,
    **FILTER,
    **TOP_BOTTOM,
}

# Sort key by length descending so longer matches are tried first
_SORTED_OPERATION_KEYWORDS: list[tuple[str, str]] = sorted(
    _OPERATION_KEYWORDS.items(), key=lambda item: len(item[0]), reverse=True
)


def _tokenize_question(question: str) -> list[str]:
    """Split a question into lowercase word tokens.

    Args:
        question: Raw user question.

    Returns:
        List of lowercase word tokens.
    """
    return re.findall(r"\b\w+\b", question.lower())


def _find_operation_keyword(question: str) -> tuple[str, str] | None:
    """Find the first matching operation keyword in the question.

    Longer keywords are matched before shorter ones to avoid partial matches
    (e.g., "group by" before "group"). When multiple keywords are present,
    the one that appears earliest in the question text wins.

    Args:
        question: Raw user question.

    Returns:
        A tuple of (matched_keyword, operation_name) or None if no keyword
        was found.
    """
    lower_q = question.lower()
    candidates: list[tuple[int, str, str]] = []

    for keyword, operation in _SORTED_OPERATION_KEYWORDS:
        # Use lookbehind/lookahead to avoid partial matches for non-word chars
        pattern = re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")
        for m in pattern.finditer(lower_q):
            candidates.append((m.start(), keyword, operation))

    if not candidates:
        return None

    # Sort by position in question, then by keyword length (longer wins ties)
    candidates.sort(key=lambda item: (item[0], -len(item[1])))
    _, keyword, operation = candidates[0]
    return keyword, operation


def _extract_operands_after_keyword(
    question: str, keyword: str, operation: str
) -> list[str]:
    """Extract column names that appear immediately after an operation keyword.

    The heuristic captures tokens that follow the keyword up to a stop word
    or sentence boundary. This ensures operands are only extracted when they
    are syntactically attached to the operation. For filter operations, the
    column name typically appears before the operator keyword, so both sides
    are checked.

    Args:
        question: Raw user question.
        keyword: The matched operation keyword (original case preserved from
            the question, but matching is case-insensitive).
        operation: The normalized operation name.

    Returns:
        List of extracted operand strings (preserved original casing from the
        question).
    """
    lower_q = question.lower()
    keyword_lower = keyword.lower()

    # Find the position of the keyword in the original question
    pattern = re.compile(rf"(?<!\w){re.escape(keyword_lower)}(?!\w)", re.IGNORECASE)
    match = pattern.search(question)
    if not match:
        return []

    operands: list[str] = []

    # For filter operations, check tokens before the keyword (the column)
    if operation == "filter":
        before = question[:match.start()].strip()
        before_tokens = re.findall(r"\b\w+\b", before)
        if before_tokens:
            operands.append(before_tokens[-1])
        return operands

    # Check tokens after the keyword
    start = match.end()
    remainder = question[start:].strip()

    # Stop words that typically terminate an operand list
    stop_words = {
        "by", "from", "to", "in", "on", "at", "for", "and", "or", "the",
        "a", "an", "where", "that", "which", "who", "whom", "whose",
        "than", "then", "with", "without", "between", "among",
    }

    tokens = re.findall(r"\b\w+\b", remainder)
    for token in tokens:
        if token.lower() in stop_words:
            break
        operands.append(token)

    return operands


def extract_intent(question: str) -> IntentReference:
    """Parse a user question to identify an explicit operation and its operands.

    The parser uses centralized keyword dictionaries to detect operations. Operands
    are extracted only when they appear syntactically attached to an operation
    keyword. For purely natural language questions without explicit operation
    keywords, an empty IntentReference is returned so the LLM can handle semantic
    reasoning.

    Args:
        question: The user's natural-language question about the dataset.

    Returns:
        An IntentReference containing the detected operation and any extracted
        operand column names.
    """
    if not question or not question.strip():
        return IntentReference(operation=None, operands=[])

    found = _find_operation_keyword(question)
    if found is None:
        return IntentReference(operation=None, operands=[])

    keyword, operation = found
    operands = _extract_operands_after_keyword(question, keyword, operation)

    return IntentReference(operation=operation, operands=operands)


def _resolve_schema_references(
    user_question: str, dataset_profile: dict[str, Any]
) -> SchemaResolution:
    """Validate extracted operands against the dataset schema.

    This function is the deterministic gate between the user question and the
    LLM planner. It extracts explicit column references and checks them against
    the dataset profile. Missing columns trigger fuzzy suggestions via
    difflib.get_close_matches, but suggestions are never used to bypass
    validation or trigger automatic execution.

    Args:
        user_question: The user's natural-language question.
        dataset_profile: Dataset metadata from DatasetProfiler, including the
            'columns' dictionary with column names as keys.

    Returns:
        A SchemaResolution indicating whether all operands are present in the
        schema, along with any missing columns and fuzzy suggestions.
    """
    available_columns = set(dataset_profile.get("columns", {}).keys())
    intent = extract_intent(user_question)

    if not intent.operands:
        return SchemaResolution(resolved=True, missing_columns=[], suggestions={})

    missing_columns = [col for col in intent.operands if col not in available_columns]

    if not missing_columns:
        return SchemaResolution(resolved=True, missing_columns=[], suggestions={})

    suggestions: dict[str, list[str]] = {}
    for col in missing_columns:
        matches = difflib.get_close_matches(
            col, available_columns, n=3, cutoff=0.6
        )
        if matches:
            suggestions[col] = matches

    return SchemaResolution(
        resolved=False,
        missing_columns=missing_columns,
        suggestions=suggestions,
    )


def resolve_schema_references(
    user_question: str, dataset_profile: dict[str, Any]
) -> SchemaResolution:
    """Public entry point for deterministic schema resolution.

    Wraps the internal resolution logic with logging and a stable interface
    for consumption by the planner.

    Args:
        user_question: The user's natural-language question.
        dataset_profile: Dataset metadata from DatasetProfiler.

    Returns:
        A SchemaResolution describing whether the question's explicit column
        references are valid against the dataset schema.
    """
    resolution = _resolve_schema_references(user_question, dataset_profile)

    if not resolution.resolved:
        logger.warning(
            "Schema resolution failed for question '%s': missing columns %s, suggestions %s",
            user_question,
            resolution.missing_columns,
            resolution.suggestions,
        )

    return resolution
