"""Semantic intent normalizer for the analytics planner.

This module resolves business entities and column references from user questions,
providing case-insensitive matching, singular/plural normalization, alias support,
and entity coordination. It distinguishes business entities from physical dataset
columns and does not silently discard unresolved operands.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.analytics.intent_extractor import IntentReference

logger = logging.getLogger(__name__)


@dataclass
class SemanticIntent:
    """Normalized intent with resolved column references.
    
    Attributes:
        operation: The detected analytics operation.
        target_columns: Columns directly involved in the analysis (excluding group_by).
        group_by: Columns used for grouping.
        sort_by: Primary sort column.
        sort_order: Sort direction.
        limit: Row limit for top_n operations.
        ambiguous: True when the intent relies on LLM inference rather than explicit keywords.
        hints: Operational hints for the LLM prompt.
        unresolved_entities: Business entities or tokens that could not be mapped to columns.
    """
    operation: str | None = None
    target_columns: list[str] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    sort_by: str | None = None
    sort_order: str | None = None
    limit: int | None = None
    ambiguous: bool = False
    hints: list[str] = field(default_factory=list)
    unresolved_entities: list[str] = field(default_factory=list)


# Business entity aliases that should NOT be treated as column references
# These are semantic business nouns that appear in questions but represent grouping concepts
_BUSINESS_ENTITIES: set[str] = {
    'customer', 'customers', 'order', 'orders', 'product', 'products',
    'transaction', 'transactions', 'employee', 'employees', 'state', 'states',
    'region', 'regions', 'department', 'departments', 'category', 'categories',
    'segment', 'segments', 'city', 'cities', 'country', 'countries',
    'record', 'records', 'row', 'rows', 'item', 'items', 'course', 'courses',
    'grade', 'grades', 'subject', 'subjects', 'day', 'days', 'week', 'weeks',
    'month', 'months', 'year', 'years',
}

# Column aliases for common business terms that map to actual columns
# These are used to resolve semantic phrases to actual column names
_COLUMN_ALIASES: dict[str, str] = {
    # Financial - map semantic terms to columns
    'paid amount': 'Paid',
    'paid': 'Salary',  # "paid" in employee context maps to Salary
    'sales amount': 'Sales',
    'revenue': 'Revenue',
    'price': 'Price',
    'cost': 'Cost',
    'profit': 'Profit',
    'salary': 'Salary',
    'wage': 'Salary',
    'income': 'Income',
    'rating': 'Rating',
    'score': 'Score',
    'temperature': 'Temperature',
    'returns': 'Returns',
    'population': 'Population',
    'ordercount': 'OrderCount',
    'ordervalue': 'OrderValue',
    'amount': 'amount',
    # Personal identifiers
    'age': 'age',
    'name': 'name',
    'date': 'Date',
    'time': 'Time',
}


def _normalize_singular_plural(word: str) -> str:
    """Convert plural form to singular, then to lowercase for matching.
    
    Handles common English pluralization rules.
    """
    lower = word.lower()
    
    # Already singular or not plural
    if lower in _BUSINESS_ENTITIES:
        return lower
    
    # Try removing common plural suffixes
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


def _resolve_business_entities(
    tokens: list[str],
    available_columns: set[str],
) -> tuple[list[str], list[str]]:
    """Separate business entities from genuine column references.
    
    Args:
        tokens: List of tokens from the question.
        available_columns: Set of valid column names in the dataset.
        
    Returns:
        Tuple of (column_references, business_entities).
    """
    columns = []
    entities = []
    
    # Build lowercase column set for case-insensitive matching
    lower_to_original = {col.lower(): col for col in available_columns}
    
    i = 0
    while i < len(tokens):
        token = tokens[i]
        
        # Check multi-word aliases first (longest match wins)
        matched_alias = False
        for alias, target in _COLUMN_ALIASES.items():
            alias_words = alias.split()
            if i + len(alias_words) <= len(tokens):
                candidate = " ".join(tokens[i:i + len(alias_words)]).lower()
                if candidate == alias:
                    if target in available_columns:
                        columns.append(target)
                        i += len(alias_words)
                        matched_alias = True
                        break
        if matched_alias:
            continue
        
        # Check if it's a business entity
        normalized = _normalize_singular_plural(token)
        if normalized in _BUSINESS_ENTITIES:
            entities.append(token)
            i += 1
            continue
        
        # Check if it matches a column (case-insensitive)
        if token.lower() in lower_to_original:
            columns.append(lower_to_original[token.lower()])
            i += 1
            continue
        
        # Check single-word aliases
        if token.lower() in _COLUMN_ALIASES:
            aliased = _COLUMN_ALIASES[token.lower()]
            if aliased in available_columns:
                columns.append(aliased)
                i += 1
                continue
        
        # Unknown token - could be a column or entity
        columns.append(token)
        i += 1
    
    return columns, entities


def _map_entity_to_group_column(entity: str, available_columns: set[str]) -> str | None:
    """Map a business entity to a plausible schema column for group-by."""
    lower_to_original = {c.lower(): c for c in available_columns}
    
    # First try the exact entity name (capitalized) - preserves semantic entity name
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
    
    for candidate in candidates:
        if candidate in available_columns:
            return candidate
        if candidate.lower() in lower_to_original:
            return lower_to_original[candidate.lower()]
    
    return None


def _extract_correlation_columns(question: str, available_columns: set[str]) -> list[str]:
    """Extract column names for correlation operations.
    
    Looks for patterns like:
    - "Correlation between Age and Income" → [Age, Income]
    - "Compare Age and Income" → [Age, Income]
    - "Correlation Sales Region" → [Sales, Region]
    """
    columns = []
    lower_to_original = {col.lower(): col for col in available_columns}
    q_lower = question.lower()
    
    # Pattern: "between X and Y" or "between X, Y and Z"
    between_match = re.search(r'between\s+(.+?)(?:\s*\?|\s*\.|\s*$)', question, re.IGNORECASE)
    if between_match:
        between_text = between_match.group(1)
        # Split on ' and ' to handle multiple columns
        parts = re.split(r'\s+and\s+', between_text)
        for part in parts:
            potential_cols = re.findall(r'\b\w+\b', part)
            for col in potential_cols:
                if col.lower() in lower_to_original:
                    mapped = lower_to_original[col.lower()]
                    if mapped not in columns:
                        columns.append(mapped)
                elif col.lower() not in _BUSINESS_ENTITIES and col.lower() not in {'all', 'numeric', 'columns'}:
                    if col not in columns:
                        columns.append(col)
        return columns
    
    # Pattern: "Compare X and Y"
    compare_match = re.search(r'compare\s+(.+?)(?:\s*\?|\s*\.|\s*$)', question, re.IGNORECASE)
    if compare_match:
        compare_text = compare_match.group(1)
        parts = re.split(r'\s+and\s+', compare_text)
        for part in parts:
            potential_cols = re.findall(r'\b\w+\b', part)
            for col in potential_cols:
                if col.lower() in lower_to_original:
                    mapped = lower_to_original[col.lower()]
                    if mapped not in columns:
                        columns.append(mapped)
        return columns
    
    return columns


def extract_semantic_intent(
    user_question: str,
    dataset_profile: dict[str, Any],
    raw_intent: IntentReference,
) -> SemanticIntent:
    """Build a semantic intent by resolving entities and columns.
    
    Args:
        user_question: The user's natural-language question.
        dataset_profile: Dataset metadata including columns.
        raw_intent: The raw intent extracted from the question.
        
    Returns:
        A SemanticIntent with resolved references and operational hints.
    """
    available_columns = set(dataset_profile.get("columns", {}).keys())
    
    # Get all tokens from the question
    tokens = re.findall(r'\b\w+\b', user_question)
    
    # Separate business entities from column references
    resolved_columns, entities = _resolve_business_entities(tokens, available_columns)
    
    # Build semantic intent
    intent = SemanticIntent(
        operation=raw_intent.operation,
        ambiguous=not raw_intent.operation,
    )
    
    # Add operational hints
    if raw_intent.operation:
        intent.hints.append(f"Detected operation: {raw_intent.operation}")
    
    # Resolve operands against schema
    if raw_intent.operands:
        for operand in raw_intent.operands:
            # Case-insensitive column matching
            if operand in available_columns:
                intent.target_columns.append(operand)
            else:
                lower_to_original = {col.lower(): col for col in available_columns}
                if operand.lower() in lower_to_original:
                    intent.target_columns.append(lower_to_original[operand.lower()])
                else:
                    # Keep unresolved for transparency
                    intent.unresolved_entities.append(operand)
    
    # Add business entities as unresolved (not silently discarded)
    intent.unresolved_entities.extend(entities)
    
    # Map business entities to group-by columns (preserve entity name for semantic clarity)
    q_lower = user_question.lower()
    group_patterns = [
        r'\b(?:by|per|grouped\s+by)\s+(customer|customers|order|orders|product|products|state|states|region|regions|department|departments|category|categories|segment|segments|city|cities|country|countries|employee|employees|transaction|transactions|day|days|week|weeks|month|months|year|years|course|courses|grade|grades|subject|subjects)\b',
    ]
    for pattern in group_patterns:
        matches = re.findall(pattern, q_lower)
        for entity in matches:
            mapped = _map_entity_to_group_column(entity, available_columns)
            if mapped and mapped not in intent.group_by:
                intent.group_by.append(mapped)
    
    # Special handling for correlation: extract all relevant columns
    if raw_intent.operation == "correlation" or "correlation" in q_lower:
        corr_columns = _extract_correlation_columns(q_lower, available_columns)
        for col in corr_columns:
            if col not in intent.target_columns:
                intent.target_columns.append(col)
    
    # Detect sort intent from question
    if 'sort by' in user_question.lower() or 'order by' in user_question.lower():
        intent.hints.append("Sorting detected in question")
        # Find ALL sort columns mentioned (for multi-column sort)
        sort_cols = re.findall(r'(?:sort by|order by)\s+(\w+)', user_question.lower())
        # Handle patterns like "Sort by Department then Salary descending"
        # This extracts the full text after "sort by" or "order by"
        full_match = re.search(r'(?:sort by|order by)\s+([^[.]+)', user_question.lower())
        if full_match:
            sort_text = full_match.group(1).strip()
            # Extract all potential sort columns
            potential_sorts = re.findall(r'\b\w+\b', sort_text)
            for col in potential_sorts:
                if col in available_columns:
                    if col not in intent.target_columns:
                        intent.target_columns.append(col)
                else:
                    lower_to_original = {c.lower(): c for c in available_columns}
                    if col.lower() in lower_to_original:
                        mapped = lower_to_original[col.lower()]
                        if mapped not in intent.target_columns:
                            intent.target_columns.append(mapped)
        
        # Set the primary sort column (last mentioned for multi-col sort)
        if sort_cols:
            last_col = sort_cols[-1] if sort_cols else None
            if last_col and last_col in available_columns:
                intent.sort_by = last_col
            elif last_col:
                lower_to_original = {c.lower(): c for c in available_columns}
                if last_col.lower() in lower_to_original:
                    intent.sort_by = lower_to_original[last_col.lower()]
    
    # Detect sort direction
    if 'descending' in user_question.lower() or 'desc' in user_question.lower() or 'high to low' in user_question.lower() or 'highest' in user_question.lower() or 'largest' in user_question.lower() or 'top' in q_lower:
        intent.sort_order = 'desc'
    elif 'ascending' in user_question.lower() or 'asc' in user_question.lower() or 'a to z' in user_question.lower() or 'low to high' in user_question.lower() or 'lowest' in user_question.lower() or 'bottom' in q_lower:
        intent.sort_order = 'asc'
    
    # Detect limit
    limit_match = re.search(r'\b(?:top|bottom|first|last)\s+(\d+)', user_question.lower())
    if limit_match:
        intent.limit = int(limit_match.group(1))
    
    # Detect group-by intent
    if 'by' in q_lower and raw_intent.operation:
        # Special handling for top_n: entity before "by", metric after "by"
        if raw_intent.operation == "top_n":
            topn_match = re.search(r'\b(?:top|bottom|first|last)\s+\d+\s+(.+?)\s+by\s+(\w+)', q_lower)
            if topn_match:
                entity_text = topn_match.group(1)
                metric_text = topn_match.group(2)
                # Map entity to group-by column
                entity_words = re.findall(r'\b\w+\b', entity_text)
                for word in entity_words:
                    if word.lower() in _BUSINESS_ENTITIES:
                        mapped = _map_entity_to_group_column(word, available_columns)
                        if mapped and mapped not in intent.group_by:
                            intent.group_by.append(mapped)
                    elif word.lower() in lower_to_original:
                        intent.group_by.append(lower_to_original[word.lower()])
                # Map metric to target_columns
                if metric_text.lower() in lower_to_original:
                    metric_col = lower_to_original[metric_text.lower()]
                    if metric_col not in intent.target_columns:
                        intent.target_columns.append(metric_col)
                if metric_text.lower() in _COLUMN_ALIASES:
                    aliased = _COLUMN_ALIASES[metric_text.lower()]
                    if aliased in available_columns and aliased not in intent.target_columns:
                        intent.target_columns.append(aliased)
        else:
            groupby_match = re.search(r'\bby\s+(.+?)(?:\s+where|\s+for|\s+in|$)', q_lower)
            if groupby_match:
                potential_groups = re.findall(r'\b\w+\b', groupby_match.group(1))
                for col in potential_groups:
                    # Skip non-column words
                    if col.lower() in _BUSINESS_ENTITIES:
                        mapped = _map_entity_to_group_column(col, available_columns)
                        if mapped and mapped not in intent.group_by:
                            intent.group_by.append(mapped)
                    elif col in available_columns:
                        intent.group_by.append(col)
                    else:
                        lower_to_original = {col.lower(): col for col in available_columns}
                        if col.lower() in lower_to_original:
                            intent.group_by.append(lower_to_original[col.lower()])
    
    # Detect "highest <metric> <entity> in each <group>" pattern
    if raw_intent.operation == "top_n" or "highest" in q_lower or "lowest" in q_lower:
        highest_match = re.search(r'(?:highest|lowest)\s+(?:paid|salary|revenue|score|amount|sales|profit|price|temperature|rating|returns|population|ordercount|ordervalue)\s+(?:employee|employees|customer|customers|product|products|order|orders|transaction|transactions|record|records)\s+in\s+each\s+(\w+)', q_lower)
        if highest_match:
            group_entity = highest_match.group(1)
            mapped = _map_entity_to_group_column(group_entity, available_columns)
            if mapped and mapped not in intent.group_by:
                intent.group_by.append(mapped)
            # Extract metric from the match
            metric_match = re.search(r'(?:highest|lowest)\s+(\w+)', q_lower)
            if metric_match:
                metric_word = metric_match.group(1)
                if metric_word.lower() in lower_to_original:
                    metric_col = lower_to_original[metric_word.lower()]
                    if metric_col not in intent.target_columns:
                        intent.target_columns.append(metric_col)
                if metric_word.lower() in _COLUMN_ALIASES:
                    aliased = _COLUMN_ALIASES[metric_word.lower()]
                    if aliased in available_columns and aliased not in intent.target_columns:
                        intent.target_columns.append(aliased)
    
    # Detect "Which <entity> generated the highest <metric>?" pattern
    which_match = re.search(r'which\s+(\w+)\s+generated\s+the\s+highest\s+(\w+)', q_lower)
    if which_match:
        entity_word = which_match.group(1)
        metric_word = which_match.group(2)
        if entity_word.lower() in _BUSINESS_ENTITIES:
            mapped = _map_entity_to_group_column(entity_word, available_columns)
            if mapped and mapped not in intent.group_by:
                intent.group_by.append(mapped)
        if metric_word.lower() in lower_to_original:
            metric_col = lower_to_original[metric_word.lower()]
            if metric_col not in intent.target_columns:
                intent.target_columns.append(metric_col)
        if metric_word.lower() in _COLUMN_ALIASES:
            aliased = _COLUMN_ALIASES[metric_word.lower()]
            if aliased in available_columns and aliased not in intent.target_columns:
                intent.target_columns.append(aliased)
    
    # Remove group_by columns from target_columns (but not filter columns)
    if intent.group_by:
        intent.target_columns = [
            col for col in intent.target_columns if col not in intent.group_by
        ]
    
    return intent