# Architecture Documentation

## System Architecture

Insight Sculpture follows a thin-client, server-centric architecture. The static frontend delegates all analytics, LLM communication, and session state to the FastAPI backend. There is no persistent database; uploaded datasets and their profiles live in memory for the lifetime of the backend process. All AI capabilities are provided exclusively by Google Gemini via the `google-genai` SDK.

The system is organized into four logical layers:

1. **Presentation Layer** — Static HTML5/Tailwind frontend served by Nginx.
2. **API Layer** — FastAPI routers that validate requests, manage sessions, and orchestrate the analytics pipeline.
3. **Engine Layer** — Deterministic Pandas executor, dataset profiler, chart builder, and in-memory session store.
4. **AI Layer** — Gemini-backed planner and explainer wrapped by a schema-resolution preprocessor.

## Data / Request Flow

### 1. Dataset Upload (`POST /api/upload/`)

```
Frontend (multipart/form-data)
    ↓
FastAPI upload router
    ↓
DatasetProfiler → shape, columns, sample rows, semantic types
    ↓
DatasetSessionManager → in-memory DatasetSession
    ↓
Response: session_id + profile
```

The frontend sends a CSV or Excel file. The `upload` router saves a temp file, profiles it with `DatasetProfiler`, loads the DataFrame, and stores a `DatasetSession` keyed by a UUID. The profile includes column names, inferred semantic types (`numeric`, `categorical`, `datetime`, `boolean`), missing-value statistics, and sample rows. The temp file is deleted after processing.

### 2. Standard Analysis (`POST /api/analyze/`)

```
Frontend (JSON: session_id, question, conversation_history)
    ↓
FastAPI analyze router
    ↓
DatasetSessionManager → dataset_profile + dataframe
    ↓
Intent Extractor (deterministic) → resolve schema references
    ↓
AnalysisPlanner (Gemini) → AnalysisPlan (structured JSON)
    ↓
Post-generation normalization (column casing, aliases, sort order)
    ↓
Deterministic validation of plan against dataset schema
    ↓
DataExecutor (Pandas) → ExecutionResult (dataframe + summary + metadata)
    ↓
ChartBuilder (Plotly) → ChartResult (figure JSON)
    ↓
AnalysisExplainer (Gemini) → ExplanationResult (text + key findings + follow-ups)
    ↓
Response: { analysis_plan, execution_result, chart, explanation, processing_time_ms }
```

The analyze endpoint is synchronous. It returns the full payload in one response. Chart generation failures are non-fatal; the endpoint still returns the plan, execution result, and explanation.

### 3. Streaming Analysis (`POST /api/stream/`)

```
Frontend (JSON body, Accept: text/event-stream)
    ↓
FastAPI stream router → StreamingResponse
    ↓
SSE generator:
  - connected
  - planning_started → AnalysisPlanner (Gemini)
  - planning_completed
  - execution_started → DataExecutor (Pandas)
  - execution_completed
  - chart_started → ChartBuilder (Plotly)
  - chart_completed
  - explanation_started → AnalysisExplainer (Gemini, stream_text)
  - token (repeated for each LLM chunk)
  - completed
    ↓
Frontend parses SSE frames and updates UI incrementally
```

The stream endpoint yields SSE-formatted strings. Progress milestones (planning, execution, charting) are sent as discrete events. The explanation phase streams tokens from `GeminiClient.stream_text()` inside an `asyncio` executor to avoid blocking the event loop.

### 4. LLM Interaction Pattern

Every LLM call routes through a single `GeminiClient` instance:

```
Application code
    ↓
GeminiClient.generate_text() / generate_json() / stream_text()
    ↓
_retry_with_backoff (3 attempts, exponential backoff)
    ↓
google-genai SDK → models.generate_content() or generate_content_stream()
    ↓
Response validation (text extraction, JSON parsing, Pydantic validation)
    ↓
Application exception mapping (AuthenticationError, RateLimitError, etc.)
```

Prompt engineering is centralized in `app/llm/prompts.py`. The planner receives a strict system prompt enforcing exact column-name matching and forbidding semantic substitution. The explainer receives a strict grounding prompt that prohibits invented business context.

## Component Breakdown

### Frontend (`frontend/`)

- **index.html** — Single-page dashboard with Tailwind CSS, upload widget, chat interface, and chart container.
- **js/api.js** — Base-URL resolution, `fetchWithTimeout`, SSE reader (`streamAnalysis`), and error normalization (`ApiError`).
- **js/app.js** — Application bootstrap and event wiring.
- **js/upload.js** — File selection, upload state, and profile display.
- **js/query.js** — Chat input handling and response rendering.
- **js/stream.js** — SSE event dispatch for real-time progress and explanation tokens.
- **js/chart.js** — Plotly chart rendering from `figure JSON`.
- **js/state.js** — Lightweight client state (`sessionId`, dataset metadata).
- **js/ui.js / utils.js** — Markdown rendering, formatting, shared helpers.

### API Layer (`backend/app/api/`)

- **analyze.py** — Orchestrates the full non-streaming pipeline: session validation → planning → execution → charting → explanation. Handles LLM exception translation to HTTP status codes.
- **stream.py** — Mirrors the analyze pipeline but yields SSE events. Uses `asyncio.to_thread` for blocking Pandas calls and `loop.run_in_executor` for streaming LLM text.
- **upload.py** — Validates file extension and size, profiles the dataset, creates a session, and cleans up temp files.

### Core Layer (`backend/app/core/`)

- **dependencies.py** — Singleton providers for `DatasetSessionManager`, `DatasetProfiler`, `DataExecutor`, `ChartBuilder`, and `GeminiClient`. Uses `functools.lru_cache` for instance reuse.
- **exceptions.py** — Dataclass-based exception hierarchy with `error_code`, `http_status`, and structured `to_dict()` serialization. Submodules define domain-specific errors (dataset, analytics, LLM, API).
- **middleware.py** — CORS, GZip compression, TrustedHost (production), request ID, response time, request counting, and security headers.

### LLM Layer (`backend/app/llm/`)

- **client.py** — `GeminiClient` wraps `google-genai`. Supports `generate_text`, `generate_json` (with `response_mime_type="application/json"`), and `stream_text`. Implements retry with exponential backoff and maps SDK exceptions to application exceptions.
- **planner.py** — `AnalysisPlanner` converts questions into `AnalysisPlan` objects. Runs deterministic schema resolution and semantic intent normalization before invoking the LLM. Post-processes LLM output heavily: case correction, alias resolution, compound entity handling, sort-order precedence, Top-N consolidation, and correlation filtering.
- **explainer.py** — `AnalysisExplainer` converts `ExecutionResult` objects into structured `ExplanationResult` objects (explanation text, summary, key findings, follow-up questions, confidence).
- **prompts.py** — Pure functions returning system and user prompt strings. Contains strict instructions for column-name integrity and grounded output.
- **intent_normalizer.py** — Resolves business entities and column aliases from user questions. Generates `SemanticIntent` with operational hints injected into the planner prompt.

### Analytics Layer (`backend/app/analytics/`)

- **intent_extractor.py** — Rule-based preprocessor that extracts explicit operation keywords and operands from user questions. Validates operands against the dataset schema before the LLM is called. Business entities are silently separated from genuine column references. Fuzzy match suggestions are provided but never auto-executed.
- **chart_builder.py** — `ChartBuilder` converts `ExecutionResult` objects into Plotly figures. Supports bar, line, scatter, pie, histogram, box, and heatmap charts. Validates column existence and data types before rendering.

### Supporting Modules

- **session.py** — Thread-safe in-memory `DatasetSessionManager`. Stores `DatasetSession` dataclasses containing the DataFrame, profile, and metadata. Supports expiration cleanup.
- **profiler.py** — `DatasetProfiler` generates JSON-serializable dataset metadata: shape, sample rows, per-column inferred types, numeric summaries, datetime ranges, and categorical top values.
- **schemas.py** — Pydantic models for `AnalysisPlan`, `FilterCondition`, `UserQuery`, and enumerations for `AllowedOperation`, `AggregationType`, `SortOrder`, `ChartType`, and `FilterOperator`.

## Folder Structure

```
backend/
  app/
    main.py                 # FastAPI app factory, middleware, routers, lifespan
    config.py               # Settings (env vars), Environment enum
    session.py              # In-memory session registry (thread-safe)
    profiler.py             # CSV/Excel → dataset profile
    executor.py             # Validated AnalysisPlan → Pandas ExecutionResult
    schemas.py              # Pydantic schemas & enums
    core/
      dependencies.py       # DI container (singletons)
      exceptions.py         # Error hierarchy
      middleware.py         # HTTP middleware
    api/
      analyze.py            # POST /api/analyze/
      stream.py             # POST /api/stream/
      upload.py             # POST /api/upload/
    llm/
      client.py             # Gemini API client
      planner.py            # Question → AnalysisPlan
      explainer.py          # ExecutionResult → ExplanationResult
      prompts.py            # Prompt templates
      intent_normalizer.py  # Semantic intent resolution
    analytics/
      chart_builder.py      # ExecutionResult → Plotly figure
      intent_extractor.py   # Rule-based schema resolver
  requirements.txt
  Dockerfile                # Multi-stage Python build

frontend/
  index.html                # SPA shell
  css/styles.css
  js/
    api.js                  # Network client + SSE reader
    app.js                  # App orchestration
    upload.js               # Upload UI
    query.js                # Chat UI
    stream.js               # SSE event handler
    chart.js                # Plotly chart renderer
    state.js                # Client state store
    ui.js                   # UI helpers
    utils.js                # SSE parsing, JSON safety
  nginx.conf                # Reverse proxy + static serving
  Dockerfile                # Nginx Alpine image

docs/
  PLANNER_CAPABILITY_MATRIX.md
```

## Design Decisions

### Gemini-Only LLM Strategy

The application uses a single LLM provider: Google Gemini. The `GeminiClient` is the only concrete implementation of the LLM interface. This decision simplifies dependency injection, reduces provider-specific branching, and ensures consistent prompt engineering, retry logic, and exception mapping across planning and explanation tasks.

### Deterministic Schema Resolution Before LLM Planning

User questions pass through `intent_extractor.resolve_schema_references()` before the planner is invoked. This pre-validator extracts explicit column references using keyword dictionaries and regular expressions, checks them against the dataset profile, and rejects unknown columns with fuzzy-match suggestions. This prevents the LLM from hallucinating column names and keeps the executor safe.

### Post-Generation Plan Normalization

The planner applies extensive deterministic normalization to LLM output:
- Column name casing is corrected to match the dataset profile.
- Compound dimensions (e.g., "customer segment") are resolved to unified group-by columns.
- Semantic aliases (e.g., "paid amount" → "Paid") are applied only when the target column exists.
- Top-N queries with group-by are consolidated into a single `top_n` operation.
- Correlation operations are restricted to numeric columns.
- Sort order is resolved through a strict precedence hierarchy: explicit user direction > semantic ranking keywords > default metric heuristic.

This hybrid approach lets the LLM handle ambiguous semantics while ensuring the executor always receives a valid, executable plan.

### In-Memory Sessions Without Persistence

Sessions are stored in a thread-safe in-memory dictionary. This choice reflects the current scale: sessions are ephemeral, the application is designed for single-process or single-container deployment, and there is no multi-user authentication requirement. If horizontal scaling or session durability becomes necessary, the `DatasetSessionManager` interface can be backed by Redis or a relational database without changing the API layer.

### Static Frontend with ES Modules

The frontend is a static HTML5 application with no build step. Tailwind CSS is loaded via CDN, and JavaScript is organized as ES modules. This minimizes deployment complexity and allows Nginx to serve the frontend directly. Chart.js is used for quick inline visualizations, while Plotly figures are rendered from backend-generated JSON.

### SSE Streaming Over WebSockets

Real-time progress uses Server-Sent Events rather than WebSockets. SSE is unidirectional (server → client), which matches the application's need to stream progress and explanation tokens without requiring client-to-server message framing. The implementation manually parses SSE frames over a `fetch()` stream because native `EventSource` does not support POST requests or custom headers.

### Multi-Stage Docker Build

The backend Dockerfile uses a multi-stage build to keep the final image minimal. Dependencies are installed in a builder stage and copied into a slim runtime image that runs as a non-root user. The frontend uses an Nginx Alpine base with gzip enabled and security headers configured.
