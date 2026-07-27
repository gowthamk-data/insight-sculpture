# Insight Sculpture

AI-Powered Data Analytics Assistant that converts natural language questions into structured analyses, visualizations, and plain-language explanations.

## Project Overview

Insight Sculpture is a conversational analytics platform that lets users upload tabular datasets (CSV, XLSX, XLS) and query them using natural language. The backend uses an LLM-driven planner to translate questions into executable analysis plans, a deterministic Pandas executor to compute results, a Plotly chart builder for visualizations, and an LLM explainer to narrate findings. The application is designed for local or containerized deployment with a static HTML5 frontend and a FastAPI backend.

## Key Features

- **Dataset Upload** — Ingest CSV and Excel files with automatic profiling and session management.
- **Natural Language Querying** — Ask questions in plain English; the planner generates structured analysis plans.
- **Deterministic Execution** — Validated plans run through a Pandas executor supporting summarize, filter, aggregate, groupby, sort, top_n, and correlation operations.
- **Chart Generation** — Automatic Plotly chart recommendation and rendering (bar, line, scatter, pie, histogram, box, heatmap).
- **AI Explanations** — The explainer converts verified results into concise, grounded natural-language summaries with follow-up questions.
- **SSE Streaming** — Real-time progress updates and token-level explanation streaming via Server-Sent Events.
- **Schema Integrity** — A deterministic schema resolution layer validates column references before LLM planning to prevent hallucinated column names.
- **Production-Ready Docker** — Multi-service Docker Compose setup with Nginx frontend and health-checked FastAPI backend.

## Workflow
User Question
↓
Intent Extraction
↓
Planner (Gemini)
↓
Validated Plan
↓
Pandas Executor
↓
Plotly
↓
Explainer (Gemini)
↓
Frontend


## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | HTML5, Tailwind CSS (CDN), Chart.js, Vanilla ES Modules |
| Backend | FastAPI, Uvicorn, Python 3.12 |
| LLM | Google Gemini (`google-genai` SDK) |
| Data Processing | Pandas, NumPy |
| Visualization | Plotly |
| Validation | Pydantic v2 |
| Containerization | Docker, Docker Compose, Nginx |

## Project Structure

```
insight-sculpture/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI application factory
│   │   ├── config.py               # Environment configuration & validation
│   │   ├── session.py              # In-memory dataset session store
│   │   ├── profiler.py             # Dataset profiling & metadata
│   │   ├── executor.py             # Deterministic Pandas analytics executor
│   │   ├── schemas.py              # Pydantic schemas for plans & queries
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── analyze.py          # POST /api/analyze/
│   │   │   ├── stream.py           # POST /api/stream/ (SSE)
│   │   │   └── upload.py           # POST /api/upload/
│   │   ├── core/
│   │   │   ├── dependencies.py     # Dependency injection container
│   │   │   ├── exceptions.py       # Centralized exception hierarchy
│   │   │   └── middleware.py       # CORS, GZip, security headers
│   │   ├── llm/
│   │   │   ├── client.py           # Gemini API client
│   │   │   ├── planner.py          # Natural language → AnalysisPlan
│   │   │   ├── explainer.py        # Execution results → explanations
│   │   │   ├── intent_normalizer.py # Semantic intent resolution
│   │   │   └── prompts.py          # Prompt templates
│   │   └── analytics/
│   │       ├── chart_builder.py    # Plotly chart generation
│   │       └── intent_extractor.py # Deterministic schema resolution
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html                  # Single-page dashboard
│   ├── css/styles.css
│   ├── js/
│   │   ├── api.js                  # Fetch + SSE client
│   │   ├── app.js                  # Application orchestration
│   │   ├── upload.js               # Dataset upload UI
│   │   ├── query.js                # Chat/query UI
│   │   ├── stream.js               # SSE event handling               
│   │   ├── state.js                # Client state management
│   │   ├── ui.js                   # UI utilities
│   │   └── utils.js                # Helpers
│   ├── nginx.conf
│   └── Dockerfile
├── docs/
│   └── PLANNER_CAPABILITY_MATRIX.md
├── docker-compose.yml
└── .env                            # Local environment overrides (not committed)
```

## Quick Start (Docker)

1. **Set environment variables** — Create a `.env` file in the project root with:
   ```env
   GEMINI_API_KEY=your-api-key
   GEMINI_MODEL=models/gemini-2.5-flash-lite
   ENVIRONMENT=production
   DEBUG=false
   ```

2. **Build and start** — From the project root:
   ```bash
   docker compose up --build -d
   ```

3. **Access the application** — Open `http://localhost` in a browser.

4. **Verify health**:
   ```bash
   curl http://localhost/health
   curl http://localhost/api/health
   ```

5. **Stop services**:
   ```bash
   docker compose down
   ```

## Environment Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key. |
| `GEMINI_MODEL` | No | `models/gemini-2.5-flash-lite` | Gemini model identifier. |
| `APP_NAME` | No | `Insight Sculpture` | Application display name. |
| `ENVIRONMENT` | No | `development` | Runtime mode: `development` or `production`. |
| `DEBUG` | No | `true` (dev) / `false` (prod) | Enable debug logging. Must be `false` in production. |
| `HOST` | No | `127.0.0.1` | Backend bind address. |
| `PORT` | No | `8000` | Backend port (1–65535). |

## API Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/upload/` | POST | Upload a CSV/Excel dataset. Returns `session_id`, shape, and dataset profile. |
| `/api/analyze/` | POST | Run a full non-streaming analysis. Returns plan, execution result, chart, and explanation. |
| `/api/stream/` | POST | Stream analysis progress and explanation via SSE (`text/event-stream`). |
| `/` | GET | API metadata and version. |
| `/health` | GET | Health check with uptime and environment. |
| `/ready` | GET | Readiness probe. |
| `/live` | GET | Liveness probe. |

**Development-only:** `/docs` (Swagger UI) and `/redoc` are available when `ENVIRONMENT=development`.

## Usage Instructions

1. **Upload a dataset** — Use the dashboard to select a CSV or Excel file. The backend profiles the dataset and returns a `session_id`.
2. **Ask a question** — Type a natural-language question about the dataset in the chat interface.
3. **Choose interaction mode**:
   - **Standard** — The frontend calls `/api/analyze/` and displays the complete result.
   - **Streaming** — The frontend opens an SSE connection to `/api/stream/` for real-time progress and token-by-token explanation delivery.
4. **Review results** — The response includes the validated analysis plan, execution result summary, optional Plotly chart, and a grounded natural-language explanation with suggested follow-up questions.

## Screenshots

> Screenshots are not available in this repository. Placeholders for future assets:

- **Dashboard Upload View** — `assets/screenshots/upload-view.png`
- **Analysis Chat Interface** — `assets/screenshots/chat-view.png`
- **Chart Output Example** — `assets/screenshots/chart-output.png`
- **SSE Streaming Progress** — `assets/screenshots/streaming-view.png`
