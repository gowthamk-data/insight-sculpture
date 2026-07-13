# Insight Sculpture — Architecture Analysis & Findings

> Status: Analysis only (no files modified). This document summarizes how the
> application is structured, the coding style, and the architectural
> inconsistencies / missing pieces found before continued development.

## 1. Application Overview

**Insight Sculpture** is a "conversational AI-powered data analytics platform."
A user uploads a CSV/XLSX/XLS dataset, then asks natural-language questions. The
backend uses an LLM to (1) plan an analysis, (2) deterministically execute it over
the in-memory dataframe, (3) build a Plotly chart, and (4) generate a natural-language
explanation. It also exposes an SSE streaming endpoint that replays the same pipeline
with token-by-token explanation.

Stack: **FastAPI** (Python 3) backend, **vanilla JS + Tailwind (CDN)** frontend,
**OpenAI** as the only implemented LLM provider, **pandas** for analytics.

### Request flow
```
[upload] POST /api/upload
   -> DatasetProfiler.profile_file() + _load_dataset() (twice)
   -> DatasetSessionManager.create_session()  (in-memory, uuid)
   -> returns session_id + profile

[analyze] POST /api/analyze   (synchronous, full structured JSON)
   -> AnalysisPlanner.plan()        (LLM -> AnalysisPlan via generate_json)
   -> DataExecutor.execute()        (deterministic pandas over session df)
   -> ChartBuilder.build_chart()    (Plotly figure)
   -> AnalysisExplainer.explain()   (LLM -> ExplanationResponse via generate_json)

[stream] POST /api/stream    (SSE, text/event-stream)
   -> replays the same 4 stages inline, streams explanation tokens via llm_client.stream_text()
```

## 2. Directory / Module Map

```
backend/app/
  main.py                 FastAPI factory, inline middleware, health endpoints, exception handlers
  config.py               Settings (pydantic), env loading, provider enum
  schemas.py              UserQuery (unused), FilterCondition, AnalysisPlan, enums
  executor.py             DataExecutor — deterministic pandas operations
  profiler.py             DatasetProfiler — dataset -> LLM-safe profile
  session.py              DatasetSessionManager — thread-safe in-memory store
  openai_client.py        EMPTY FILE (0 bytes) — shadow of the real client below
  api/  analyze.py upload.py stream.py
  core/ dependencies.py exceptions.py middleware.py
  llm/  client.py openai_client.py (real) explainer.py planner.py prompts.py
  analytics/ chart_builder.py
frontend/
  index.html
  assets/app.js           EMPTY FILE (0 bytes) — duplicate of assets/js/app.js
  assets/styles.css       EMPTY FILE (0 bytes) — duplicate of assets/css/styles.css
  assets/js/  api.js upload.js chat.js stream.js app.js
  assets/js/charts.js     MISSING (referenced by index.html)
  assets/js/ui.js         MISSING (referenced by index.html)
  assets/css/styles.css   (full stylesheet; NOT loaded by index.html — only Tailwind CDN used)
backend/Dockerfile        EMPTY DIRECTORY (not a file) — no container build
.env                      present but EMPTY (no OPENAI_API_KEY configured)
```

## 3. Coding Style (observed)
- Heavy docstrings + module-level "this module does X, NOT Y" contracts.
- Dependency injection via `app.core.dependencies` (`@lru_cache` singletons).
- Pydantic v2 schemas with `extra="forbid"`.
- Exceptions as dataclasses / custom classes; extensive `try/except` per stage.
- Frontend: class-per-module (`ApiClient`, `UploadManager`, `ChatManager`,
  `StreamManager`), global `window.*` exports, CustomEvent pub/sub between modules.
- No tests, no README, no frontend build step, no linter config present.

## 4. Architectural Inconsistencies & Missing Pieces

### CRITICAL — app will not run / will not load
1. **`plotly` is not in `backend/requirements.txt`** but `analytics/chart_builder.py`
   does `import plotly.express as px` / `import plotly.graph_objects as go`.
   → FastAPI import fails on startup. **Add `plotly`.**
2. **`python-multipart` is not in `requirements.txt`** but `upload.py` uses
   `File(...)` (multipart/form-data). → FastAPI raises "python-multipart not
   installed" at request time. **Add `python-multipart`.**
3. **`frontend/assets/js/api.js` line 206 is a syntax error:**
   `the abortController = new AbortController();` (stray `the `).
   → The entire `api.js` fails to parse → `window.API` is never defined →
   `UploadManager`/`ChatManager`/`StreamManager` throw on init → whole UI dies.
   **Fix to `const abortController = new AbortController();`.**

### HIGH — broken/missing frontend wiring
4. **`charts.js` and `ui.js` are referenced in `index.html` but do not exist.**
   `app.js` guards with `typeof ... !== 'function'` so it won't crash, but
   `Modules.charts`/`Modules.ui` stay `null` → Visualization + Insights sections
   never render and there is no charts/UI module. **Create the files or remove
   the `<script>` tags / init calls.**
5. **Streaming is initialized but never used by the UI.** `ChatManager.sendMessage`
   always calls `apiClient.analyze()` (synchronous). The `StreamManager` is built
   and `window.initializeStream` exists, but nothing connects the Send button to
   `stream.connect()`. The `/api/stream` endpoint is effectively dead code from
   the user's perspective.

### HIGH — backend design inconsistencies
6. **Two divergent LLM client implementations.**
   - `app/llm/client.py` → `LLMClient` (its own exceptions, `NotImplementedError`
     for Anthropic). Exported by `llm/__init__.py`. Largely **dead code** in the
     live path (DI uses the other one).
   - `app/llm/openai_client.py` → `OpenAIClient` / `BaseLLMClient` (the one actually
     used by `dependencies.get_llm_client`).
   - Plus an empty `app/openai_client.py` that shadows the `llm/` one by name.
   → Confusing, easy to import the wrong one. **Pick one client; delete the
   empty/stray files; align `llm/__init__.py` exports.**
7. **Two parallel exception hierarchies that don't line up.**
   - `app/llm/client.py` defines `LLMError, AuthenticationError, RateLimitError,
     NetworkError, TimeoutError` — these are the ones `planner/explainer/stream`
     catch and the ones `main.py` handlers catch.
   - `app/core/exceptions.py` defines a *separate* `InsightSculptureError` tree
     (`LLMError`, `AuthenticationError`, `ProviderConfigurationError`,
     `DependencyError`, etc.) used by `dependencies.py` (DI raises these).
   - `main.py` has **no handler** for the core `InsightSculptureError` family.
     Example: a missing API key makes `get_llm_client()` raise
     `core.AuthenticationError`/`ProviderConfigurationError`, which escape to the
     generic `Exception` handler → opaque 500. **Unify on one hierarchy
     (recommend `app/core/exceptions.py`) and register handlers for it, or have
     DI translate to the client exceptions the handlers expect.**
8. **Middleware duplication / dead `core/middleware.py`.**
   `main.py._configure_middleware` defines inline request-id/timing/security
   middleware and its own CORS origins, and **never calls**
   `core.middleware.register_middlewares()`. The well-structured
   `core/middleware.py` (RequestIDMiddleware, LoggingMiddleware,
   ErrorHandlingMiddleware, `get_cors_origins`, `get_trusted_hosts`) is unused.
   → Two sources of truth for CORS + security headers. **Use
   `register_middlewares()` in `main.py`, delete the inline versions, or vice
   versa — but only one.**

### MEDIUM — logic / correctness gaps
9. **Session cleanup is never invoked.** `DatasetSessionManager.cleanup_expired_sessions()`
   exists but no background task/scheduler calls it. Sessions (full dataframes)
   accumulate in memory forever → memory leak. **Add a startup `asyncio` task or
   TTL eviction.**
10. **`stream.py` reconnection is non-functional.** `StreamManager._attemptReconnection`
    increments the retry counter and schedules a `setTimeout` that only dispatches
    an event — it never re-calls `_initiateStream`. So after retries are exhausted
    the stream is dead. **Wire the timer to actually reconnect (the class already
    has a `reconnect` method).**
11. **`stream.py` explanation path duplicates `AnalysisExplainer`** (manual prompt
    build + `llm_client.stream_text`) instead of reusing `explainer`. Two
    explanation code paths can drift. **Reuse `AnalysisExplainer` (or share
    prompt helpers) in the stream path.**
12. **`stream.py` `_stream_text_async` blocks the event loop.** It runs
    `llm_client.stream_text()` in a thread to *get* the generator, then iterates
    that blocking generator on the event loop (`for token in stream`). Network I/O
    in the generator executes synchronously on the loop thread. **Stream tokens via
    `async for` against a true async client, or iterate the generator inside the
    executor.**
13. **`upload.py` reads the file twice** — `profiler.profile_file()` then
    `profiler._load_dataset()` (a *private* method). **Reuse the dataframe already
    loaded by the profiler, or have `profile_file` return the df.**

### LOW — hygiene / dead code
14. **`schemas.UserQuery` is unused** (APIs define their own `AnalyzeRequest` /
    `StreamRequest` which duplicate it). **Remove or consolidate.**
15. **`analyze.py` `AnalyzeRequest.field_validator`** is a no-op `classmethod`
    (not a registered validator). Dead code.
16. **Empty/dead files:** `backend/app/openai_client.py`, `frontend/assets/app.js`,
    `frontend/assets/styles.css`. **Delete.**
17. **Anthropic listed as a provider** (`config.py`, `requirements.txt`) but every
    path raises `NotImplementedError` / `ProviderConfigurationError`. Either
    implement it or remove the option to avoid a misleading config surface.
18. **Routing inconsistency:** `/api/upload|analyze|stream` are prefixed, but
    `/`, `/health`, `/ready`, `/live` are not. Acceptable, but decide a convention.
19. **`temp_uploads/` is created under `Path.cwd()`** at upload time; in some
    deployments CWD may be read-only. Use a configured/temp dir.

## 5. Recommended Remediation Order
1. Fix the three blockers so the app boots and the UI loads: add `plotly` +
   `python-multipart` to requirements; fix `api.js` line 206; create or remove
   `charts.js`/`ui.js` references. (CRITICAL/HIGH)
2. Resolve the duplication: single LLM client, single exception hierarchy with
   registered handlers, single middleware source. (HIGH)
3. Wire streaming into the chat UX and fix reconnection/event-loop blocking. (HIGH)
4. Add session TTL cleanup + reuse profiled dataframe in upload. (MEDIUM)
5. Delete dead files/stubs, consolidate duplicate schemas/validators. (LOW)

## 6. Validation (after fixes)
- `pip install -r backend/requirements.txt` then `python -c "import app.main"`
  must succeed (proves plotly/multipart + import graph OK).
- Run `node --check frontend/assets/js/api.js` (and each JS file) — must pass.
- Boot `uvicorn app.main:app` and `curl` `/health`; `POST /api/upload` with a
  sample CSV; `POST /api/analyze`; confirm structured JSON (plan/result/chart/
  explanation) returns 200.
- Open `index.html` and confirm no 404s in network tab and a successful upload →
  question → chart + insights render.
