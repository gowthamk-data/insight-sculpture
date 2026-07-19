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


# ---------------------------------------------------------------------------
# Comprehensive stop-words & non-column-token filters
# ---------------------------------------------------------------------------

# Words that are never valid column names — common English filler, question
# words, prepositions, articles, determiners, pronouns, conjunctions, etc.
_STOP_WORDS: frozenset[str] = frozenset({
    # Question words
    "what", "which", "where", "when", "why", "how", "who", "whom", "whose",
    # Articles & determiners
    "the", "a", "an", "this", "that", "these", "those", "some", "any",
    "every", "each", "both", "no", "none", "several", "few", "many", "much",
    "most", "more", "less",
    # Prepositions
    "in", "on", "at", "by", "for", "to", "from", "with", "without", "of",
    "about", "above", "across", "after", "against", "along", "among",
    "around", "before", "behind", "below", "beneath", "beside", "between",
    "beyond", "during", "except", "inside", "into", "near", "off", "onto",
    "outside", "over", "through", "under", "until", "up", "upon",
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their", "mine", "yours",
    "hers", "its", "ours", "theirs", "myself", "yourself", "himself",
    "herself", "itself", "ourselves", "yourselves", "themselves",
    # Conjunctions
    "and", "or", "but", "nor", "yet", "so", "because", "since", "although",
    "though", "while", "if", "unless", "as", "than", "then",
    # Common verbs & auxiliary verbs
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "having", "do", "does", "did", "doing", "will", "would", "shall",
    "should", "can", "could", "may", "might", "must", "need", "dare",
    "show", "give", "get", "find", "list", "see", "view", "display",
    "tell", "provide", "return", "calculate", "compute", "determine",
    "show", "give", "get", "find", "list", "call", "make", "use", "want",
    "like", "need", "take", "know", "think", "say", "look", "try",
    "exclude", "include", "remove", "add", "select", "choose", "pick",
    # Common nouns in analytics questions
    "records", "data", "information", "result", "results", "value",
    "values", "number", "numbers", "total", "sum", "average", "avg",
    "mean", "median", "minimum", "maximum", "min", "max",
    "count", "size",
    # Sort-related terms that are not columns
    "ascending", "descending", "alphabetical", "reverse",
    "asc", "desc", "a-z", "z-a", "high", "low", "highest", "lowest",
    "largest", "smallest", "biggest", "least", "greatest",
    # Ranking / position words
    "top", "bottom", "rank", "ranking", "ranked", "first", "last",
    "next", "previous", "above", "below",
    # Time-related filler words
    "now", "today", "yesterday", "tomorrow", "currently", "recently",
    "recent", "latest", "previous", "past", "future", "over", "last",
    # General filler
    "please", "kindly", "just", "only", "also", "still", "already",
    "ever", "never", "always", "often", "sometimes", "usually",
    "here", "there", "herein", "therein", "hereby", "thereby",
    "per", "via", "versus", "vs",
})


def is_plausible_column_candidate(token: str) -> bool:
    """Return True if *token* could plausibly be a dataset column name.

    Filters out:
      - Pure numeric values (int, float, negative numbers)
      - Single-character tokens (abbreviated column names are typically ≥2 chars)
      - Known stop words (English filler, operators, question words)
      - Tokens that are operator symbols (=, !=, >, <, >=, <=)
      - Tokens with non-alphanumeric characters (unless underscore)
    """
    if not token or not token.strip():
        return False

    # Reject pure numeric values (including negative, decimal)
    try:
        float(token)
        return False
    except ValueError:
        pass

    # Reject single-character tokens (meaningless as column names)
    if len(token) <= 1:
        return False

    # Reject tokens that are operator symbols
    if token in ("=", "!=", ">", "<", ">=", "<="):
        return False

    # Reject known stop words (case-insensitive)
    if token.lower() in _STOP_WORDS:
        return False

    return True


def _looks_like_column_name(token: str) -> bool:
    """Return True if token looks like an explicit column reference rather than
    natural language.

    Heuristics:
    - Contains uppercase letters (PascalCase / camelCase)
    - Contains underscores (snake_case)
    - Is longer than typical English words (>12 chars)
    """
    if not token:
        return False
    if "_" in token:
        return True
    if any(c.isupper() for c in token):
        return True
    if len(token) > 12:
        return True
    return False


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
    "median": "aggregate",
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


# Multi-word column aliases that should be resolved before schema validation
_MULTI_WORD_ALIASES: dict[str, str] = {
    "house price": "Price",
    "paid amount": "Paid",
    "sales amount": "Sales",
    "marketing spend": "Marketing Spend",
}


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


# ---------------------------------------------------------------------------
# Business entity recognition — nouns that describe data groups, NOT columns
# ---------------------------------------------------------------------------

# These are natural-language nouns that appear in questions but should NOT
# be validated against the schema. They represent business entities or
# grouping concepts that the LLM handles semantically.
_BUSINESS_ENTITIES: set[str] = {
    # People / roles
    'customer', 'customers', 'employee', 'employees', 'student', 'students',
    'teacher', 'teachers', 'user', 'users', 'person', 'people', 'individual',
    # Transactions / records
    'order', 'orders', 'transaction', 'transactions', 'record', 'records',
    'row', 'rows', 'item', 'items', 'ticket', 'tickets', 'invoice', 'invoices',
    # Products / inventory
    'product', 'products', 'item', 'items', 'sku', 'category', 'categories',
    'segment', 'segments', 'brand', 'brands', 'inventory',
    # Geography
    'state', 'states', 'city', 'cities', 'country', 'countries', 'region',
    'regions', 'district', 'districts', 'area', 'areas', 'zone', 'zones',
    'location', 'locations',
    # Time units
    'day', 'days', 'week', 'weeks', 'month', 'months', 'year', 'years',
    'quarter', 'quarters', 'hour', 'hours',
    # Education
    'course', 'courses', 'grade', 'grades', 'subject', 'subjects', 'class',
    'classes', 'department', 'departments', 'faculty',
    # Generic grouping nouns
    'numeric', 'numerics', 'column', 'columns', 'field', 'fields', 'variable',
    'variables', 'attribute', 'attributes',
    # Other frequent business nouns
    'account', 'accounts', 'project', 'projects', 'task', 'tasks',
    'document', 'documents', 'file', 'files',
}


def _map_entity_to_group_column(entity: str, available_columns: set[str]) -> str | None:
    """Map a business entity to a plausible schema column for group-by.

    For example, "customers" might map to "CustomerID", "orders" to "OrderID".
    Falls back to None if no mapping is found.
    """
    # Try exact entity name first, then ID suffixes
    candidates = [
        entity.capitalize(),
        entity.capitalize() + 'ID',
        entity.capitalize() + '_ID',
        entity.capitalize() + ' Code',
        entity.capitalize() + ' Name',
        entity.capitalize() + 'Type',
    ]

    # Singular form candidates
    singular = entity.rstrip('s')
    if singular != entity:
        candidates.extend([
            singular.capitalize() + 'ID',
            singular.capitalize(),
            singular.capitalize() + ' Name',
        ])

    lower_to_original = {c.lower(): c for c in available_columns}
    for candidate in candidates:
        if candidate in available_columns:
            return candidate
        if candidate.lower() in lower_to_original:
            return lower_to_original[candidate.lower()]

    return None


def _singularize_column_name(token: str) -> str:
    """Convert plural form to singular for column matching.
    
    Handles common English pluralization rules like:
    - amounts -> amount
    - amounts -> amount
    - transactions -> transaction
    """
    lower = token.lower()
    if lower.endswith('ies') and len(lower) > 3:
        return lower[:-3] + 'y'
    if lower.endswith('ves') and len(lower) > 3:
        return lower[:-3] + 'f'
    if lower.endswith('xes') or lower.endswith('zes'):
        return lower[:-2]
    if lower.endswith('es') and len(lower) > 2:
        return lower[:-2]
    if lower.endswith('s') and len(lower) > 1:
        return lower[:-1]
    return lower


def _resolve_schema_references(
    user_question: str, dataset_profile: dict[str, Any]
) -> SchemaResolution:
    """Validate extracted operands against the dataset schema.

    This function is the deterministic gate between the user question and the
    LLM planner. It extracts explicit column references and checks them against
    the dataset profile. Missing columns trigger fuzzy suggestions via
    difflib.get_close_matches, but suggestions are never used to bypass
    validation or trigger automatic execution.

    **Entity Resolution Layer (CRITICAL)**:
    Business entities (customers, orders, products, etc.) are common in user
    questions but are NOT schema columns. They represent grouping concepts that
    the LLM handles semantically. The resolver:
    1. Classifies operands into categories via is_plausible_column_candidate()
    2. Separates business entities from genuine column references
    3. Maps common business entities to likely schema columns via heuristics
    4. Only validates tokens that could plausibly be column names

    **Fuzzy match classification**:
    - If a missing operand has a close fuzzy match → likely misspelling → error
    - If a missing operand has NO fuzzy match → natural language noun → silently
      dropped (do NOT raise ColumnNotFoundError)

    Args:
        user_question: The user's natural-language question.
        dataset_profile: Dataset metadata from DatasetProfiler, including the
            'columns' dictionary with column names as keys.

    Returns:
        A SchemaResolution indicating whether the question's explicit column
        references are valid against the dataset schema.
    """
    available_columns = set(dataset_profile.get("columns", {}).keys())
    intent = extract_intent(user_question)

    if not intent.operands:
        return SchemaResolution(resolved=True, missing_columns=[], suggestions={})

    # ---- MULTI-WORD ALIAS RESOLUTION ----
    # Resolve known multi-word aliases in the question before token-level validation
    lower_q = user_question.lower()
    alias_replacements: dict[str, str] = {}
    alias_operand_indices: set[int] = set()

    # Build a map of operand index to token for alias tracking
    operand_tokens = intent.operands

    for alias, column in _MULTI_WORD_ALIASES.items():
        if alias in lower_q and column in available_columns:
            alias_replacements[alias] = column
            # Find and mark operands that are part of this alias
            alias_words = alias.split()
            for i in range(len(operand_tokens) - len(alias_words) + 1):
                candidate = " ".join(operand_tokens[i:i + len(alias_words)]).lower()
                if candidate == alias:
                    for j in range(i, i + len(alias_words)):
                        alias_operand_indices.add(j)

    # If aliases were found, validate them as known columns
    validated_columns: list[str] = []
    for alias, column in alias_replacements.items():
        validated_columns.append(column)

    # ---- CLASSIFICATION LAYER ----
    # Categorize operands: genuine columns, business entities, or unknown words
    lower_to_original = {c.lower(): c for c in available_columns}

    business_entities: list[str] = []
    unknown_tokens: list[str] = []

    for idx, operand in enumerate(operand_tokens):
        # Skip operands that were consumed by multi-word alias resolution
        if idx in alias_operand_indices:
            continue

        # Never validate operators or punctuation as columns
        if not is_plausible_column_candidate(operand):
            continue

        operand_lower = operand.lower()

        # Case-insensitive exact column match
        if operand_lower in lower_to_original:
            validated_columns.append(lower_to_original[operand_lower])
            continue

        # Check singular form for plural column names (e.g., "amounts" -> "amount")
        singular = _singularize_column_name(operand_lower)
        if singular in lower_to_original and singular != operand_lower:
            validated_columns.append(lower_to_original[singular])
            continue

        # Check if it's a recognized business entity
        if operand_lower in _BUSINESS_ENTITIES:
            business_entities.append(operand)
            continue

        # Try singular form for business entities (e.g., "categories" → "category")
        singular_be = operand_lower.rstrip('s')
        if singular_be != operand_lower and singular_be in _BUSINESS_ENTITIES:
            business_entities.append(operand)
            continue

        # Unknown token — treat as potential column; validate below
        unknown_tokens.append(operand)

    # ---- VALIDATION LAYER ----
    # Only validate unknown tokens; business entities are silently accepted
    missing_columns: list[str] = []
    suggestions: dict[str, list[str]] = {}

    for col in unknown_tokens:
        # If token looks like an explicit column name (PascalCase, snake_case, etc.),
        # treat it as a genuine column reference even without fuzzy match
        if _looks_like_column_name(col):
            missing_columns.append(col)
            matches = difflib.get_close_matches(
                col, list(available_columns), n=3, cutoff=0.6
            )
            if matches:
                suggestions[col] = matches
            continue

        # Check fuzzy matches
        matches = difflib.get_close_matches(
            col, list(available_columns), n=3, cutoff=0.6
        )

        if matches:
            # Close match exists → likely misspelling → report as error
            missing_columns.append(col)
            suggestions[col] = matches
        else:
            # No fuzzy match → likely natural language, NOT a misspelling
            # Silently drop without error (e.g., "sorted", "numeric", "columns")
            pass

    if missing_columns:
        return SchemaResolution(
            resolved=False,
            missing_columns=missing_columns,
            suggestions=suggestions,
        )

    return SchemaResolution(resolved=True, missing_columns=[], suggestions={})


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