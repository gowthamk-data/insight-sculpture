# Planner Capability Matrix

> **Status:** Canonical Benchmark  
> **Owner:** QA / Data Engineering  
> **Last Updated:** 2026-07-17  
> **Purpose:** Objective, quantitative evaluation of the Analytics Planner's ability to convert natural-language analytical questions into valid `AnalysisPlan` objects.

---

## 1. Capability Inventory

### 1.1 Operations

| Category | Operation | Enum Value | Description |
|---|---|---|---|
| Summary | Summarize | `summarize` | Return dataset statistics and sample data |
| Filtering | Filter | `filter` | Apply deterministic row-selection conditions |
| Aggregation | Aggregate | `aggregate` | Compute a single summary statistic over target columns |
| Grouping | GroupBy | `groupby` | Group by one or more dimensions and aggregate |
| Sorting | Sort | `sort` | Order rows by one or more columns |
| Ranking | Top N | `top_n` | Return the top or bottom N rows after sorting |
| Statistical | Correlation | `correlation` | Compute a numeric correlation matrix |

### 1.2 Aggregation Functions

| Aggregation | Enum Value | Numeric Only | Typical Synonyms |
|---|---|---|---|
| Sum | `sum` | Yes | total, sum of |
| Mean | `mean` | Yes | average, avg, mean of |
| Median | `median` | Yes | median, middle |
| Count | `count` | No | count, number of, how many |
| Min | `min` | Yes | minimum, lowest, smallest |
| Max | `max` | Yes | maximum, highest, largest |
| Standard Deviation | `std` | Yes | std, standard deviation, spread |

### 1.3 Filter Operators

| Operator | Enum Value | Symbol | Typical Synonyms |
|---|---|---|---|
| Equals | `=` | `=` | equals, equal, is |
| Not Equals | `!=` | `!=` | not equals, not equal, is not, != |
| Greater Than | `>` | `>` | greater than, above, exceeds |
| Less Than | `<` | `<` | less than, below, under |
| Greater Than or Equal | `>=` | `>=` | at least, no less than |
| Less Than or Equal | `<=` | `<=` | at most, no more than |
| Contains | `contains` | — | contains, includes, has |

### 1.4 Sort Directions

| Direction | Enum Value | Typical Synonyms |
|---|---|---|
| Ascending | `asc` | ascending, ascending order, low to high, A-Z |
| Descending | `desc` | descending, descending order, high to low, Z-A |

### 1.5 Chart Types

| Chart | Enum Value | Typical Use Case |
|---|---|---|
| None | `none` | No visualization requested or appropriate |
| Bar | `bar` | Categorical comparison |
| Line | `line` | Time-series or trend data |
| Pie | `pie` | Part-to-whole proportions |
| Scatter | `scatter` | Correlation or distribution |
| Histogram | `histogram` | Numeric distribution |

### 1.6 Plan Fields (Schema)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `operation` | `AllowedOperation` | Yes | — | Primary analytics operation |
| `target_columns` | `list[str]` | No | `[]` | Columns directly involved in the analysis |
| `group_by` | `list[str]` | No | `[]` | Columns used for grouping |
| `filters` | `list[FilterCondition]` | No | `[]` | Pre-execution row filters |
| `aggregation` | `AggregationType` | No | `null` | Aggregation function for aggregate/groupby |
| `sort_by` | `str` | No | `null` | Column used for sorting |
| `sort_order` | `SortOrder` | No | `null` | Sort direction |
| `limit` | `int` | No | `null` | Max rows for sort/top_n |
| `chart_type` | `ChartType` | No | `none` | Recommended visualization |
| `explanation_required` | `bool` | No | `true` | Whether to generate an explanation |

### 1.7 Validation Constraints

| Rule | Scope | Description |
|---|---|---|
| Aggregation required | `aggregate`, `groupby` | These operations must specify an `aggregation` function |
| GroupBy columns required | `groupby` | Must specify at least one `group_by` column |
| SortBy + Limit required | `top_n` | Must specify both `sort_by` and a positive `limit` |
| Target columns required | `correlation` | Must specify at least one `target_column` |
| Column existence | All | Every column in `target_columns`, `group_by`, `sort_by`, and `filters` must exist in the dataset schema |
| Unique columns | `target_columns`, `group_by` | No duplicate column names within each list |
| Filter operator enum | `filters` | Operator must be one of the 7 allowed `FilterOperator` values |
| Sort order enum | `sort_order` | Must be `asc` or `desc` when provided |
| Limit positivity | `limit` | Must be a positive integer when provided |

---

## 2. Capability Matrix

| Capability | Supported | Representative Questions | Expected Planner Output / Operation |
|---|---|---|---|
| **Summarize dataset** | True | "Summarize the dataset" | `operation: summarize` |
| **Summarize specific columns** | True | "Summarize Sales and Profit" | `operation: summarize`, `target_columns: [Sales, Profit]` |
| **Filter by equals** | True | "Show records where City = Chennai" | `operation: filter`, `filters: [{column: City, operator: =, value: Chennai}]` |
| **Filter by not equals** | True | "Exclude rows where Status = cancelled" | `operation: filter`, `filters: [{column: Status, operator: !=, value: cancelled}]` |
| **Filter by greater than** | True | "Show sales greater than 1000" | `operation: filter`, `filters: [{column: Sales, operator: >, value: 1000}]` |
| **Filter by less than** | True | "Show records where age < 30" | `operation: filter`, `filters: [{column: age, operator: <, value: 30}]` |
| **Filter by greater than or equal** | True | "Show orders with amount >= 500" | `operation: filter`, `filters: [{column: amount, operator: >=, value: 500}]` |
| **Filter by less than or equal** | True | "Show employees with salary <= 75000" | `operation: filter`, `filters: [{column: salary, operator: <=, value: 75000}]` |
| **Filter by contains** | True | "Show customers with name containing 'Smith'" | `operation: filter`, `filters: [{column: name, operator: contains, value: Smith}]` |
| **Multiple filters (AND)** | True | "Show sales > 1000 in Chennai" | `operation: filter`, `filters: [{column: Sales, operator: >, value: 1000}, {column: City, operator: =, value: Chennai}]` |
| **Aggregate SUM** | True | "What is the total sales?" | `operation: aggregate`, `aggregation: sum`, `target_columns: [Sales]` |
| **Aggregate MEAN** | True | "What is the average salary?" | `operation: aggregate`, `aggregation: mean`, `target_columns: [Salary]` |
| **Aggregate MEDIAN** | True | "What is the median house price?" | `operation: aggregate`, `aggregation: median`, `target_columns: [Price]` |
| **Aggregate COUNT** | True | "How many customers are there?" | `operation: aggregate`, `aggregation: count`, `target_columns: [CustomerID]` |
| **Aggregate MIN** | True | "What is the minimum score?" | `operation: aggregate`, `aggregation: min`, `target_columns: [Score]` |
| **Aggregate MAX** | True | "What is the maximum temperature?" | `operation: aggregate`, `aggregation: max`, `target_columns: [Temperature]` |
| **Aggregate STD** | True | "What is the standard deviation of returns?" | `operation: aggregate`, `aggregation: std`, `target_columns: [Returns]` |
| **GroupBy single column** | True | "Total sales by Region" | `operation: groupby`, `group_by: [Region]`, `aggregation: sum`, `target_columns: [Sales]` |
| **GroupBy multiple columns** | True | "Average salary by Department and Location" | `operation: groupby`, `group_by: [Department, Location]`, `aggregation: mean`, `target_columns: [Salary]` |
| **GroupBy with COUNT** | True | "Count of orders by Customer" | `operation: groupby`, `group_by: [Customer]`, `aggregation: count`, `target_columns: [OrderID]` |
| **Sort ascending** | True | "Sort by Date ascending" | `operation: sort`, `sort_by: Date`, `sort_order: asc` |
| **Sort descending** | True | "Sort by Salary descending" | `operation: sort`, `sort_by: Salary`, `sort_order: desc` |
| **Sort multiple columns** | True | "Sort by Department then Salary descending" | `operation: sort`, `sort_by: Salary`, `sort_order: desc`, `target_columns: [Department, Salary]` |
| **Top N** | True | "Top 10 customers by sales" | `operation: top_n`, `sort_by: Sales`, `sort_order: desc`, `limit: 10` |
| **Bottom N** | True | "Bottom 5 products by rating" | `operation: top_n`, `sort_by: Rating`, `sort_order: asc`, `limit: 5` |
| **Correlation** | True | "Correlation between Age and Income" | `operation: correlation`, `target_columns: [Age, Income]` |
| **Filter + Aggregate** | True | "Average salary for employees in Chennai" | `operation: aggregate`, `filters: [{column: City, operator: =, value: Chennai}]`, `aggregation: mean`, `target_columns: [Salary]` |
| **Filter + GroupBy** | True | "Total sales by Region for Electronics" | `operation: groupby`, `filters: [{column: Category, operator: =, value: Electronics}]`, `group_by: [Region]`, `aggregation: sum`, `target_columns: [Sales]` |
| **GroupBy + Sort** | True | "Average salary by Department sorted descending" | `operation: groupby`, `group_by: [Department]`, `aggregation: mean`, `target_columns: [Salary]`, `sort_by: Salary`, `sort_order: desc` |
| **GroupBy + Top N** | True | "Top 5 departments by total sales" | `operation: top_n`, `group_by: [Department]`, `aggregation: sum`, `target_columns: [Sales]`, `sort_by: Sales`, `sort_order: desc`, `limit: 5` |
| **Filter + Sort** | True | "Show high-value transactions sorted by date" | `operation: sort`, `filters: [{column: Amount, operator: >, value: 10000}]`, `sort_by: Date` |
| **Filter + Top N** | True | "Top 10 records where status = active" | `operation: top_n`, `filters: [{column: Status, operator: =, value: active}]`, `sort_by: <implied>`, `limit: 10` |
| **Aggregate + Chart** | True | "Show average salary as a bar chart" | `operation: aggregate`, `aggregation: mean`, `target_columns: [Salary]`, `chart_type: bar` |
| **GroupBy + Chart** | True | "Show sales by region as a pie chart" | `operation: groupby`, `group_by: [Region]`, `aggregation: sum`, `target_columns: [Sales]`, `chart_type: pie` |
| **Correlation + Chart** | True | "Show correlation matrix as a heatmap" | `operation: correlation`, `target_columns: [Age, Income]`, `chart_type: scatter` |
| **Summarize + Chart** | True | "Show distribution of age as a histogram" | `operation: summarize`, `target_columns: [Age]`, `chart_type: histogram` |
| **Explanation required** | True | "Explain the total sales" | `explanation_required: true` |
| **No explanation** | True | "Just show the data" | `explanation_required: false` |

---

## 3. Planner Test Dataset

### 3.1 Individual Operations

#### Aggregations (7 functions)

| ID | Question | Expected Operation | Expected Aggregation | Expected Target Columns |
|---|---|---|---|---|
| AGG-01 | "What is the total sales?" | `aggregate` | `sum` | `[Sales]` |
| AGG-02 | "Calculate the average salary" | `aggregate` | `mean` | `[Salary]` |
| AGG-03 | "What is the mean temperature?" | `aggregate` | `mean` | `[Temperature]` |
| AGG-04 | "Find the median house price" | `aggregate` | `median` | `[Price]` |
| AGG-05 | "How many customers are there?" | `aggregate` | `count` | `[CustomerID]` |
| AGG-06 | "What is the minimum score?" | `aggregate` | `min` | `[Score]` |
| AGG-07 | "What is the maximum profit?" | `aggregate` | `max` | `[Profit]` |
| AGG-08 | "What is the standard deviation of returns?" | `aggregate` | `std` | `[Returns]` |

#### Filtering (7 operators)

| ID | Question | Expected Operation | Expected Filters |
|---|---|---|---|
| FIL-01 | "Show records where City = Chennai" | `filter` | `[{column: City, operator: =, value: Chennai}]` |
| FIL-02 | "Exclude rows where Status = cancelled" | `filter` | `[{column: Status, operator: !=, value: cancelled}]` |
| FIL-03 | "Show sales greater than 1000" | `filter` | `[{column: Sales, operator: >, value: 1000}]` |
| FIL-04 | "Show records where age < 30" | `filter` | `[{column: age, operator: <, value: 30}]` |
| FIL-05 | "Show orders with amount >= 500" | `filter` | `[{column: amount, operator: >=, value: 500}]` |
| FIL-06 | "Show employees with salary <= 75000" | `filter` | `[{column: salary, operator: <=, value: 75000}]` |
| FIL-07 | "Show customers with name containing Smith" | `filter` | `[{column: name, operator: contains, value: Smith}]` |

#### Grouping

| ID | Question | Expected Operation | Expected GroupBy | Expected Aggregation |
|---|---|---|---|---|
| GRP-01 | "Total sales by Region" | `groupby` | `[Region]` | `sum` |
| GRP-02 | "Average salary by Department" | `groupby` | `[Department]` | `mean` |
| GRP-03 | "Count of orders by Customer" | `groupby` | `[Customer]` | `count` |
| GRP-04 | "Median price by Category" | `groupby` | `[Category]` | `median` |
| GRP-05 | "Total sales by Region and Segment" | `groupby` | `[Region, Segment]` | `sum` |
| GRP-06 | "Average score by Grade and Subject" | `groupby` | `[Grade, Subject]` | `mean` |

#### Sorting

| ID | Question | Expected Operation | Expected SortBy | Expected SortOrder |
|---|---|---|---|---|
| SRT-01 | "Sort by Date ascending" | `sort` | `Date` | `asc` |
| SRT-02 | "Sort by Salary descending" | `sort` | `Salary` | `desc` |
| SRT-03 | "Order by Name A to Z" | `sort` | `Name` | `asc` |
| SRT-04 | "Order by Score high to low" | `sort` | `Score` | `desc` |
| SRT-05 | "Sort by Department then Salary descending" | `sort` | `Salary` | `desc` |

#### Ranking (Top N)

| ID | Question | Expected Operation | Expected Limit | Expected SortOrder |
|---|---|---|---|---|
| TOP-01 | "Top 10 customers by sales" | `top_n` | `10` | `desc` |
| TOP-02 | "Bottom 5 products by rating" | `top_n` | `5` | `asc` |
| TOP-03 | "Top 3 highest paid employees" | `top_n` | `3` | `desc` |
| TOP-04 | "Lowest 10 transaction amounts" | `top_n` | `10` | `asc` |

#### Correlation

| ID | Question | Expected Operation | Expected Target Columns |
|---|---|---|---|
| COR-01 | "Correlation between Age and Income" | `correlation` | `[Age, Income]` |
| COR-02 | "Show correlation matrix for all numeric columns" | `correlation` | `[Age, Income, Score]` |

### 3.2 Mixed / Complex Queries

| ID | Question | Expected Operation | Key Expected Fields |
|---|---|---|---|
| MIX-01 | "Top 10 customers by total sales" | `top_n` | `sort_by: Sales`, `sort_order: desc`, `limit: 10`, `group_by: [Customer]`, `aggregation: sum`, `target_columns: [Sales]` |
| MIX-02 | "Average salary by department sorted descending" | `groupby` | `group_by: [Department]`, `aggregation: mean`, `target_columns: [Salary]`, `sort_by: Salary`, `sort_order: desc` |
| MIX-03 | "Total sales for customers in Chennai" | `aggregate` | `filters: [{column: City, operator: =, value: Chennai}]`, `aggregation: sum`, `target_columns: [Sales]` |
| MIX-04 | "Count of orders by Region where Amount > 1000" | `groupby` | `group_by: [Region]`, `aggregation: count`, `target_columns: [OrderID]`, `filters: [{column: Amount, operator: >, value: 1000}]` |
| MIX-05 | "Top 5 products by sales in Electronics category" | `top_n` | `group_by: [Product]`, `aggregation: sum`, `target_columns: [Sales]`, `filters: [{column: Category, operator: =, value: Electronics}]`, `sort_by: Sales`, `sort_order: desc`, `limit: 5` |
| MIX-06 | "Average salary by department for employees in Mumbai" | `groupby` | `group_by: [Department]`, `aggregation: mean`, `target_columns: [Salary]`, `filters: [{column: City, operator: =, value: Mumbai}]` |
| MIX-07 | "Show top 20 transactions sorted by date" | `top_n` | `sort_by: Date`, `sort_order: desc`, `limit: 20` |
| MIX-08 | "Total revenue by month for 2024" | `groupby` | `group_by: [Month]`, `aggregation: sum`, `target_columns: [Revenue]`, `filters: [{column: Year, operator: =, value: 2024}]` |
| MIX-09 | "Correlation between Marketing Spend and Revenue by Region" | `correlation` | `target_columns: [Marketing Spend, Revenue]`, `group_by: [Region]` |
| MIX-10 | "Show customers with more than 5 orders" | `filter` | `filters: [{column: OrderCount, operator: >, value: 5}]` |
| MIX-11 | "Top 10 states by population" | `top_n` | `group_by: [State]`, `aggregation: sum`, `target_columns: [Population]`, `sort_by: Population`, `sort_order: desc`, `limit: 10` |
| MIX-12 | "Average order value by customer segment" | `groupby` | `group_by: [Segment]`, `aggregation: mean`, `target_columns: [OrderValue]` |
| MIX-13 | "Show the highest paid employee in each department" | `groupby` | `group_by: [Department]`, `aggregation: max`, `target_columns: [Salary]` |
| MIX-14 | "Number of transactions per day for the last week" | `groupby` | `group_by: [Date]`, `aggregation: count`, `target_columns: [TransactionID]` |
| MIX-15 | "Products with price between 100 and 500 sorted by rating" | `filter` + `sort` | `filters: [{column: Price, operator: >=, value: 100}, {column: Price, operator: <=, value: 500}]`, `sort_by: Rating`, `sort_order: desc` |

### 3.3 Edge Cases and Ambiguity

| ID | Question | Rationale |
|---|---|---|
| EDGE-01 | "How much money was collected?" | Natural language without explicit column; should allow LLM to resolve |
| EDGE-02 | "Which course generated the highest revenue?" | Contains implicit column "revenue" that may not exist verbatim |
| EDGE-03 | "Show me everything" | Should map to `summarize` |
| EDGE-04 | "Give me the data" | Should map to `summarize` |
| EDGE-05 | "List all records" | Should map to `filter` with no filters (or summarize) |
| EDGE-06 | "What is the average?" | Missing operand; LLM must infer or request clarification |
| EDGE-07 | "Group by" | Missing group-by column; invalid plan |
| EDGE-08 | "Top N" | Missing limit and sort column; invalid plan |
| EDGE-09 | "Sales by region over time" | Implicit time-series grouping; may require date column inference |
| EDGE-10 | "Compare Age and Income" | Could map to `correlation` or `groupby`; ambiguity test |
| EDGE-11 | "Show paid amount" | Column name may be `Paid`; tests exact column matching |
| EDGE-12 | "Total salary by course" | Mismatched semantics (salary vs course); tests semantic hallucination guardrails |
| EDGE-13 | "Average of all numeric columns" | Tests multi-column aggregation inference |
| EDGE-14 | "Filter out nulls" | Tests absence of null-handling operator |
| EDGE-15 | "Show me the top and bottom 5" | Compound ranking; tests single-operation limitation |

---

## 4. Coverage Summary

Use the following checklist to audit the planner's functional reach. Mark each dimension as **Pass** (planner handles correctly), **Fail** (planner fails), or **N/A** (not applicable to current dataset).

### 4.1 Operations Coverage

- [ ] `summarize` — full dataset summary
- [ ] `summarize` — targeted column summary
- [ ] `filter` — single filter condition
- [ ] `filter` — multiple AND conditions
- [ ] `aggregate` — with `sum`
- [ ] `aggregate` — with `mean`
- [ ] `aggregate` — with `median`
- [ ] `aggregate` — with `count`
- [ ] `aggregate` — with `min`
- [ ] `aggregate` — with `max`
- [ ] `aggregate` — with `std`
- [ ] `groupby` — single column
- [ ] `groupby` — multiple columns
- [ ] `groupby` — with each aggregation type (sum, mean, median, count, min, max, std)
- [ ] `sort` — ascending
- [ ] `sort` — descending
- [ ] `sort` — multiple sort columns
- [ ] `top_n` — top N
- [ ] `top_n` — bottom N
- [ ] `correlation` — two numeric columns
- [ ] `correlation` — three or more numeric columns

### 4.2 Filter Operator Coverage

- [ ] `=` (equals)
- [ ] `!=` (not equals)
- [ ] `>` (greater than)
- [ ] `<` (less than)
- [ ] `>=` (greater than or equal)
- [ ] `<=` (less than or equal)
- [ ] `contains` (substring, case-insensitive)

### 4.3 Grouping Complexity Coverage

- [ ] Single `group_by` column
- [ ] Two `group_by` columns
- [ ] Three or more `group_by` columns
- [ ] `group_by` with `target_columns` (aggregation target)
- [ ] `group_by` with `filters` (pre-filtered grouping)
- [ ] `group_by` with `sort_by` (sorted grouped result)
- [ ] `group_by` with `limit` (top N groups)

### 4.4 Sorting Coverage

- [ ] `sort_by` with `sort_order: asc`
- [ ] `sort_by` with `sort_order: desc`
- [ ] `sort_by` without explicit `sort_order` (defaults to asc)
- [ ] `sort_by` on a non-target column
- [ ] `sort_by` on a `group_by` column (post-aggregation sort)

### 4.5 Ranking Coverage

- [ ] `top_n` with `sort_order: desc` (top N)
- [ ] `top_n` with `sort_order: asc` (bottom N)
- [ ] `top_n` with `limit` = 1 (single highest/lowest)
- [ ] `top_n` with `limit` > 100 (large N)

### 4.6 Statistical Coverage

- [ ] `correlation` with exactly 2 numeric columns
- [ ] `correlation` with 3+ numeric columns
- [ ] `correlation` with non-numeric columns (should fail gracefully)
- [ ] Numeric-only aggregations (`sum`, `mean`, `median`, `std`) on string columns (should fail gracefully)
- [ ] `count` on string columns (should succeed)

### 4.7 Schema Resolution Coverage

- [ ] Valid explicit column references pass resolver
- [ ] Invalid explicit column references raise `ColumnNotFoundError`
- [ ] Natural language questions without explicit columns bypass resolver
- [ ] Fuzzy suggestions populated for close misspellings
- [ ] No suggestions for completely unrelated column names
- [ ] Case-sensitive column matching enforced
- [ ] Column substitution prevented (e.g., "Salary" not mapped to "Paid")

### 4.8 Prompt Instruction Coverage

- [ ] Exact column names preserved in plan
- [ ] No semantic column substitution
- [ ] No invented business terminology
- [ ] No auto-correction of user inputs
- [ ] Valid JSON schema adherence (no extra fields like `columns` or `aggregation_functions`)

### 4.9 Error Handling Coverage

- [ ] `ColumnNotFoundError` returns HTTP 400
- [ ] `ColumnNotFoundError` includes `did_you_mean` suggestions
- [ ] `InvalidQuestionError` returns HTTP 400
- [ ] `InvalidDatasetProfileError` returns HTTP 422
- [ ] `PlanningError` returns HTTP 422
- [ ] LLM errors return HTTP 500
- [ ] Empty result after filters returns error

### 4.10 Mixed Operation Coverage

- [ ] Filter + Aggregate
- [ ] Filter + GroupBy
- [ ] Filter + Sort
- [ ] Filter + Top N
- [ ] GroupBy + Sort
- [ ] GroupBy + Top N
- [ ] GroupBy + Chart
- [ ] Aggregate + Chart
- [ ] Correlation + Chart
- [ ] Summarize + Chart

---

## Appendix A: Capability Coverage Scorecard

| Dimension | Total Items | Pass | Fail | N/A | Coverage % |
|---|---|---|---|---|---|
| Operations | 21 | — | — | — | — |
| Filter Operators | 7 | — | — | — | — |
| Grouping Complexity | 7 | — | — | — | — |
| Sorting | 5 | — | — | — | — |
| Ranking | 4 | — | — | — | — |
| Statistical | 5 | — | — | — | — |
| Schema Resolution | 7 | — | — | — | — |
| Prompt Instructions | 5 | — | — | — | — |
| Error Handling | 7 | — | — | — | — |
| Mixed Operations | 10 | — | — | — | — |
| **Total** | **78** | — | — | — | — |

> **Usage:** Run the full test suite against this matrix. Record Pass/Fail/N/A for each item. Compute coverage percentages to track planner regression or improvement over time.

---

## Appendix B: Execution Contract

Every `AnalysisPlan` produced by the planner must satisfy the following contract before execution:

1. **Schema Valid:** All column references exist in the dataset profile.
2. **Enum Valid:** All enum fields (`operation`, `aggregation`, `sort_order`, `chart_type`, `filter.operator`) contain allowed values.
3. **Operation Complete:** Operation-specific required fields are present (e.g., `top_n` requires `sort_by` + `limit`).
4. **Unique Columns:** `target_columns` and `group_by` contain no duplicates.
5. **JSON Schema:** Output contains exactly the specified fields — no extras, no missing required fields.

Any plan violating this contract must be rejected before reaching the executor.
