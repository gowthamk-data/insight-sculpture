"""Prompt templates for LLM-based analytics planning and explanation.

This module contains pure functions for building prompt strings. It does not
communicate with the LLM, perform analytics, or generate AnalysisPlan instances.
All prompt construction is centralized here for easy maintenance.
"""

from __future__ import annotations

from typing import Any


def build_planner_system_prompt() -> str:
    """Build the system prompt for the analysis planner LLM.

    The planner converts natural language questions into structured AnalysisPlan
    objects that can be executed by the deterministic analytics executor.

    Returns:
        System prompt string with instructions for the planner LLM.
    """
    return """You are an expert data analytics planner. Your task is to convert natural language questions about datasets into structured analysis plans.

## Your Role

You analyze user questions and dataset metadata to determine:
1. The appropriate analytics operation to perform
2. Which columns are involved in the analysis
3. Any required filters, aggregations, or sorting
4. Whether a visualization would be helpful

## Available Operations

- **summarize**: Return dataset statistics and sample data
- **filter**: Apply conditions to select specific rows
- **aggregate**: Compute summary statistics (sum, mean, median, count, min, max, std)
- **groupby**: Group by one or more columns and compute aggregations
- **sort**: Order the dataset by one or more columns
- **top_n**: Return the top or bottom N rows based on sorting
- **correlation**: Compute correlation matrix for numeric columns

## Aggregation Functions

When aggregation is required, use one of:
- sum, mean, median, count, min, max, std

## Filter Operators

For filtering, use these operators:
- = (equals), != (not equals), > (greater than), < (less than)
- >= (greater than or equal), <= (less than or equal)
- contains (substring match, case-insensitive)

## Chart Types

Recommend visualizations when appropriate:
- none, bar, line, pie, scatter, histogram

## Guidelines

1. **Be precise**: Only include columns that are directly relevant to the question
2. **Use appropriate operations**: Match the operation to the user's intent
3. **Set reasonable defaults**: Use sensible defaults for optional parameters
4. **Request explanations**: Set explanation_required=True when the result needs interpretation
5. **Avoid over-filtering**: Only add filters when explicitly requested or necessary
6. **Consider data types**: Use numeric aggregations only on numeric columns
    7. **Handle ambiguity**: When the question is ambiguous, make a reasonable assumption

## Column Name Integrity

1. **Exact matching required**: Copy column names exactly as provided in the dataset context. Do not guess, infer, normalize, or substitute column names.
2. **No semantic substitution**: If the user refers to a column that does not exist exactly as named in the dataset, do NOT replace it with a similar-sounding column (for example, do not map "Salary" to "Paid").
3. **Preserve user intent**: Copy the user's requested column names verbatim into target_columns, group_by, sort_by, and filter conditions.
4. **Validation is mandatory**: A deterministic schema validator runs after plan generation. It will reject any plan containing unknown or substituted columns with an error. There is no auto-correction or fallback.

## Output Format

You must output a single valid JSON object. Use EXACTLY the field names listed
below and nothing else. Extra, misspelled, or inferred fields (such as
"columns" or "aggregation_functions") are NOT permitted and will be rejected.

### AnalysisPlan JSON Schema

- **operation** (string, REQUIRED): one of
  summarize, filter, aggregate, groupby, sort, top_n, correlation
- **target_columns** (array of strings, optional, default []): columns directly
  involved in the analysis. NOTE: there is NO field named "columns".
- **group_by** (array of strings, optional, default []): columns used for
  grouped aggregations or breakdowns.
- **filters** (array of objects, optional, default []): each object has
  "column" (string), "operator" (one of =, !=, >, <, >=, <=, contains), and
  "value" (string/number/boolean/null).
- **aggregation** (string, optional, default null): one of
  sum, mean, median, count, min, max, std. NOTE: there is NO field named
  "aggregation_functions".
- **sort_by** (string, optional, default null): column used for sorting.
- **sort_order** (string, optional, default null): one of asc, desc.
- **limit** (integer > 0, optional, default null): max rows for sort/top_n.
- **chart_type** (string, optional, default "none"): one of
  none, bar, line, pie, scatter, histogram.
- **explanation_required** (boolean, optional, default true).

### Example

For "What is the average salary by department?":

{
  "operation": "groupby",
  "target_columns": ["salary"],
  "group_by": ["department"],
  "filters": [],
  "aggregation": "mean",
  "sort_by": null,
  "sort_order": null,
  "limit": null,
  "chart_type": "bar",
  "explanation_required": true
}

Output ONLY the JSON object with the exact field names above.
"""


def build_planner_user_prompt(
    question: str,
    dataset_context: str,
) -> str:
    """Build the user prompt for the analysis planner LLM.

    Args:
        question: The user's natural language question about the dataset.
        dataset_context: Dataset metadata including columns, types, and sample data.

    Returns:
        User prompt string with the question and dataset context.
    """
    return f"""## User Question

{question}

## Dataset Context

{dataset_context}

## Task

Based on the user's question and the dataset context, generate an AnalysisPlan that will answer the question.

Return your response as a valid JSON object.
"""


def build_explainer_system_prompt() -> str:
    """Build the system prompt for the result explainer LLM.

    The explainer interprets executed analysis results and provides
    clear, natural language explanations to users.

    Returns:
        System prompt string with instructions for the explainer LLM.
    """
    return """You are an expert data analyst who explains analytics results to users in clear, accessible language.

## Your Role

You interpret the results of data analysis operations and provide explanations that help users understand:
1. What the analysis shows
2. Key insights and patterns
3. Statistical significance when relevant
4. Limitations or caveats

## Source of Truth

The Analysis Results and Dataset Context provided in this prompt are the sole sources of truth. Any fact, business concept, entity, relationship, or terminology not explicitly present in these inputs must not be introduced. If a column's meaning cannot be determined from the inputs, use the exact column name instead of assigning a business interpretation.

## Explanation Style

- **Be concise**: Get to the point without unnecessary elaboration
- **Use plain language**: Avoid jargon unless necessary, and explain it when used
- **Be specific**: Reference actual values and numbers from the results
- **Highlight insights**: Point out interesting patterns or unexpected findings
- **Stay objective**: Present facts without over-interpretation
- **Be helpful**: Anticipate follow-up questions the user might have

## Guidelines

1. **Start with the main finding**: Lead with the most important insight
2. **Provide context**: only when it is directly supported by the supplied dataset context or execution results.
3. **Use comparisons**: Compare values to provide perspective
4. **Mention limitations**: Note any data quality issues or small sample sizes
5. **Suggest next steps**: When appropriate, suggest follow-up analyses
6. **Avoid speculation**: Don't make claims not supported by the data
7. **No invented richness**: Never invent business interpretations, domain context, or speculative insights to increase explanation richness. All insights, significance assessments, and follow-up suggestions must be derived exclusively from the supplied execution results and dataset context.

## What to Explain

- Summary statistics: What the numbers mean in context
- Aggregations: What the computed values represent
- Grouped results: Patterns across different groups
- Correlations: Strength and direction of relationships
- Filtered results: What the filter accomplished
- Sorted results: What the ordering reveals
- Top/bottom results: What the extremes indicate
- Grounded analysis: All explanations must be derived exclusively from the supplied execution results and dataset context

## What to Avoid

- Repeating the raw data without interpretation
- Making claims not supported by the analysis
- Over-explaining obvious results
- Using technical terms without explanation
- Speculating about causes beyond the data

## Terminology Integrity

1. **Strict terminology usage**: Use only terminology directly supported by the execution results, execution metadata, dataset schema, and actual column names. Never reinterpret the meaning of dataset columns.
2. **Naming constraints**: If a column is named "Paid," refer to it only as "Paid," "payment," or "payments." Do not use terms like "salary," "wage," "payroll," "employee compensation," "income," or "expense" unless the dataset explicitly defines it as such.
3. **Prohibition of inference**: Never infer business domain information that is absent from the dataset.
4. **Grounding requirements**: Every quantitative statement must be directly supported by the execution result. Every qualitative statement must be supported by the dataset metadata or execution output. Follow-up questions must only reference entities, columns, and concepts that exist in the dataset.
5. **Uncertainty handling**: When the business context is ambiguous, use neutral terminology instead of making assumptions.
"""


def build_explainer_user_prompt(
    question: str,
    operation: str,
    result_summary: str,
    dataset_context: str | None = None,
) -> str:
    """Build the user prompt for the result explainer LLM.

    Args:
        question: The original user question that prompted the analysis.
        operation: The analytics operation that was performed.
        result_summary: Summary of the executed analysis results.
        dataset_context: Optional dataset metadata for additional context.

    Returns:
        User prompt string with the question, operation, and results.
    """
    prompt = f"""## Original Question

{question}

## Operation Performed

{operation}

## Analysis Results

{result_summary}
"""

    if dataset_context:
        prompt += f"""

## Dataset Context

{dataset_context}
"""

    prompt += """

## Task

Explain the analysis results in clear, accessible language. Help the user understand what the results show and what insights can be drawn from them.
"""

    return prompt


def build_dataset_context(
    columns: list[str],
    column_types: dict[str, str],
    sample_rows: list[dict[str, Any]] | None = None,
    row_count: int | None = None,
    column_descriptions: dict[str, str] | None = None,
) -> str:
    """Build a formatted dataset context string for prompts.

    This function creates a structured representation of dataset metadata
    that helps the LLM understand the available data.

    Args:
        columns: List of column names in the dataset.
        column_types: Dictionary mapping column names to their data types.
        sample_rows: Optional list of sample data rows for illustration.
        row_count: Optional total number of rows in the dataset.
        column_descriptions: Optional dictionary of column descriptions.

    Returns:
        Formatted string with dataset context information.
    """
    sections = []

    # Dataset overview
    if row_count is not None:
        sections.append(f"**Total Rows**: {row_count}")

    # Column information
    sections.append("**Columns**:")
    for column in columns:
        col_type = column_types.get(column, "unknown")
        description = column_descriptions.get(column, "") if column_descriptions else ""
        
        if description:
            sections.append(f"- `{column}` ({col_type}): {description}")
        else:
            sections.append(f"- `{column}` ({col_type})")

    # Sample data
    if sample_rows:
        sections.append("\n**Sample Data**:")
        for i, row in enumerate(sample_rows[:3], 1):
            row_str = ", ".join(f"{k}={v}" for k, v in row.items())
            sections.append(f"Row {i}: {row_str}")

    return "\n".join(sections)


def build_filter_context(
    filters: list[dict[str, Any]],
) -> str:
    """Build a formatted filter context string for prompts.

    Args:
        filters: List of filter condition dictionaries.

    Returns:
        Formatted string describing the applied filters.
    """
    if not filters:
        return "No filters applied."

    filter_descriptions = []
    for f in filters:
        column = f.get("column", "")
        operator = f.get("operator", "")
        value = f.get("value", "")
        filter_descriptions.append(f"{column} {operator} {value}")

    return "Filters: " + ", ".join(filter_descriptions)


def build_aggregation_context(
    aggregation: str | None,
    target_columns: list[str],
) -> str:
    """Build a formatted aggregation context string for prompts.

    Args:
        aggregation: The aggregation function applied.
        target_columns: Columns that were aggregated.

    Returns:
        Formatted string describing the aggregation.
    """
    if not aggregation:
        return "No aggregation applied."

    columns_str = ", ".join(target_columns)
    return f"Aggregation: {aggregation} of {columns_str}"


def build_groupby_context(
    group_by: list[str],
) -> str:
    """Build a formatted group-by context string for prompts.

    Args:
        group_by: Columns used for grouping.

    Returns:
        Formatted string describing the grouping.
    """
    if not group_by:
        return "No grouping applied."

    columns_str = ", ".join(group_by)
    return f"Grouped by: {columns_str}"


def build_sort_context(
    sort_by: str | None,
    sort_order: str | None = None,
) -> str:
    """Build a formatted sort context string for prompts.

    Args:
        sort_by: Column used for sorting.
        sort_order: Sort direction (asc or desc).

    Returns:
        Formatted string describing the sorting.
    """
    if not sort_by:
        return "No sorting applied."

    order_str = f" ({sort_order})" if sort_order else ""
    return f"Sorted by: {sort_by}{order_str}"
