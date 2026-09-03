# Prospect Research Agent - Backend

FastAPI backend for Gunadhya's outbound-prospecting research pipeline:
CSV ingest -> qualify -> per-prospect LLM research agent -> LLM synthesis of
a connection note + 3-step email sequence -> one-page PDF brief -> human
review queue. Nothing is ever auto-sent; the terminal state of every
prospect is a PDF a human approves, edits, or rejects.

## Quick start (Windows / PowerShell)

```powershell
cd backend

# 1. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# edit .env if you want a real Anthropic key / Brave key / different DB URL

# 4. Start Postgres (via the root docker-compose.yml, or your own instance)
#    Must match backend/.env's DATABASE_URL, default:
#    postgresql://prospect:prospect@localhost:5432/prospect_research

# 5. Run migrations
alembic upgrade head

# 6. Run the app
uvicorn app.main:app --reload --port 8000
```

The app boots with **zero required configuration**: no `ANTHROPIC_API_KEY`
needed to start it, and `SEARCH_PROVIDER=mock` is the default so no search
API key is needed either. `/api/ingest` and `/api/qualify` work immediately.
`/api/prospects/{id}/research` and `/api/prospects/{id}/synthesize` return a
clean `503 {"detail": "LLM not configured, set ANTHROPIC_API_KEY"}` until you
set a real key.

### Running tests

```powershell
pip install -r requirements.txt   # includes pytest
pytest
```

Tests run against an isolated in-memory SQLite database (see
`tests/conftest.py`), not Postgres, and never call the Anthropic API or the
network -- they exercise Stage 1 ingest parsing, Stage 2 qualify filtering,
and the `record_finding` citation-validation logic directly.

## Project layout

```
backend/
  app/
    main.py               FastAPI app, CORS, router wiring
    config.py              Settings (pydantic-settings, reads .env)
    database.py             SQLAlchemy engine/session/Base
    models.py                ORM models (mirrors the spec's data model)
    schemas.py                 Pydantic v2 schemas + API request/response shapes
    deps.py                     shared FastAPI dependencies (LLM-configured guard)
    crm.py                       Stage 6: CRMAdapter Protocol + PostgresCRMAdapter
    risk_flags.py                 Stage 8: risk flag computation (read-time)
    search.py                      pluggable search(query) -> list[SearchResult]
    fetch_util.py                    httpx + trafilatura page fetch/extraction
    ids.py                             id/slug helpers
    stages/
      stage1_ingest.py               Stage 1: CSV -> Company/Prospect (plain code)
      stage2_qualify.py               Stage 2: filter/dedupe/cap (plain code)
      stage3_agent.py                  Stage 3 glue: run agent loop, persist results
      stage4_synthesize.py              Stage 4: single forced-tool-call LLM synthesis
      stage5_render.py                   Stage 5: HTML->PDF (WeasyPrint/fpdf2)
      pipeline_runner.py                  chains 3->4->5 for /pipeline/run-batch
    agent/
      tools.py                             Stage 3 tool schemas + handlers
      loop.py                               Stage 3 hand-rolled tool-use while-loop
    templates/brief.html                    Jinja2 PDF template (WeasyPrint path)
    routers/                                 one module per endpoint group
  alembic/                                    migrations (initial schema in versions/0001_initial.py)
  data/pdfs/                                    generated PDFs land here (gitignored)
  tests/                                          pytest unit tests
  requirements.txt
  .env.example
  Dockerfile
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://prospect:prospect@localhost:5432/prospect_research` | Matches the root `docker-compose.yml` Postgres service credentials exactly. |
| `ANTHROPIC_API_KEY` | unset | Required for `/research` and `/synthesize`. Unset => those endpoints return `503`. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Used for both the Stage 3 agent loop and the Stage 4 single call. |
| `SEARCH_PROVIDER` | `mock` | `mock` (default, no key, always returns `[]`), `duckduckgo` (no key, scrapes DuckDuckGo's HTML results page), or `brave`. |
| `BRAVE_API_KEY` | unset | Only used when `SEARCH_PROVIDER=brave`. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated list; Vite's default dev port. |
| `AGENT_MAX_TOOL_CALLS` | `12` | Stage 3 tool-call budget. |
| `AGENT_WALL_CLOCK_SECONDS` | `90` | Stage 3 wall-clock budget. |
| `AGENT_MAX_CONSECUTIVE_ERRORS` | `2` | Stage 3 consecutive-tool-error stop condition. |
| `QUALIFY_BATCH_CAP` | `20` | Stage 2 hard cap per qualify run. |
| `QUALIFY_HEADCOUNT_MIN` / `QUALIFY_HEADCOUNT_MAX` | `10` / `200` | Stage 2 headcount band. |
| `FETCH_TIMEOUT_SECONDS` | `15.0` | httpx timeout for the `fetch` tool. |
| `FETCH_MAX_CHARS` | `16000` | ~4000 tokens, per spec. |

## PDF rendering: WeasyPrint + fpdf2 fallback

`app/stages/stage5_render.py` always tries **WeasyPrint** first (renders
`app/templates/brief.html` via Jinja2, then HTML+CSS -> PDF). WeasyPrint
needs native GTK3/Pango/Cairo libraries that are **frequently missing on a
stock Windows machine** and are not installed by `pip install weasyprint`
alone. If the `weasyprint` import itself fails for any reason (missing DLLs,
`OSError`, etc.), the code transparently falls back to **fpdf2** -- a pure
Python, pip-installable PDF library with no system dependencies -- which
renders a simpler but still complete one-page layout covering the same
sections (header, findings table, hook strength + agent notes, connection
note, email sequence, risk flags). This was actually exercised while
building this backend: WeasyPrint installed via pip but failed to import on
this Windows dev machine, and the app fell back to fpdf2 automatically with
no code changes needed. If you want real WeasyPrint output on Windows,
install the GTK3 runtime (e.g. the MSYS2-based installer linked from the
WeasyPrint docs) and restart your shell so the DLLs are on `PATH`.

## Judgment calls / deviations from the spec

- **Unknown headcount is fail-closed.** A company with no headcount data does
  NOT auto-pass Stage 2 qualification (`app/stages/stage2_qualify.py`). The
  spec's qualification criterion is a headcount band; silently passing
  unknowns would let arbitrarily sized companies into the batch. Revisit
  once a headcount-enrichment step exists.
- **ResearchFindings / OutreachDraft are 1:1 with a Prospect, replace-on-rerun.**
  The spec's data model doesn't include a `research_run_id` anywhere, so a
  new Stage 3 run deletes and replaces the prior `Finding`/`ResearchFindings`
  rows for that prospect, and a new Stage 4 run replaces the prior
  `OutreachDraft` row. Only the latest run is retained; "one per prospect per
  research run" is satisfied in the sense that each run fully supersedes the
  last. If run history is wanted later, add a `research_run_id` column and
  stop deleting.
- **RiskFlag is not a table.** Flags are computed at **read time** in
  `app/risk_flags.py` from `Finding`/`OutreachDraft` rows already in the DB
  (called from `GET /api/prospects/{id}` and `GET /api/review-queue`). This
  avoids a persisted flag ever disagreeing with the underlying data after an
  edit, and is cheap given the small per-prospect finding count.
- **CRM = Postgres (Stage 6).** The spec suggests SQLite for the CRM
  adapter's own storage, but the whole system already runs on Postgres, so
  `PostgresCRMAdapter` (`app/crm.py`) just upserts into the same
  `companies`/`prospects` tables and writes a `crm_tasks` table + stores the
  PDF path against the prospect. This **is** the CRM for v1; the `CRMAdapter`
  Protocol is kept exactly as specified so a real external adapter can be
  substituted later without touching calling code.
- **Dedupe order** (Stage 2): `linkedin_url` first, then `(full_name,
  company_id)` fallback, checked only against prospects that have already
  progressed past `INGESTED` in a prior run -- so two rows for the same
  person within the *same* CSV upload don't spuriously dedupe against each
  other before either has been qualified.
- **Review-queue membership**: a prospect appears in `GET /api/review-queue`
  once it has status `SYNTHESIZED` or `RENDERED` and a non-disqualifying
  draft. `pdf_url` is `null` until `/render` has actually been called for
  that prospect.
- **Stage 4 second-failure handling**: if the forced `return_draft` tool call
  still fails validation after one retry, the draft is persisted anyway
  (with `claims_used` filtered down to only ids that actually exist, so the
  citation-grounding rule is never violated even in the fallback path),
  flagged `needs_human_review=True`, and the API returns `{"status":
  "ERROR", "draft": {...}}` rather than silently dropping the prospect, per
  spec.
- **`/api/pipeline/run-batch`** is best-effort: it runs Stage 2 synchronously
  (cheap, no LLM), then queues Stage 3->4->5 as one `BackgroundTasks` job per
  newly-qualified prospect. If `ANTHROPIC_API_KEY` is unset, qualify still
  runs and returns real results, but each queued job no-ops immediately
  (prospects stay at `QUALIFIED` for a manual `/research` call later) instead
  of erroring, since qualify itself succeeded.
- **Research job status** (`GET /api/prospects/{id}/research/status`) is
  derived from `Prospect.status` in the DB plus a small in-memory
  `dict[prospect_id, str]` that only tracks an *unhandled exception escaping
  the background task wrapper itself* (the agent loop is designed to never
  raise and always persist a `BUDGET_EXHAUSTED`/`ERROR` result, so this is a
  last line of defense, not the primary signal). This in-memory map is
  per-process and resets on restart -- acceptable for a single-worker
  internal tool; swap for a DB-backed job table if you run multiple workers.
- **Eval metrics best-effort**: `hook_recall` is a *proxy* (fraction of
  researched prospects with `hook_strength >= 2`), since true recall needs a
  labeled ground-truth set this system doesn't collect.
  `disqualification_precision` is always `null` in v1 -- disqualified
  prospects never reach the review queue, so there's no human label to check
  the system's disqualification decision against. `citation_validity` and
  `avg_edit_distance` are computed for real from stored `OutreachDraft`/
  `ReviewAction` rows and are `null` only when no data exists yet.
- **City/headcount normalization is intentionally simple** (Stage 1):
  city normalization is a casing/whitespace lookup for a fixed list of
  Pune-area spellings, not a geocoder; headcount ranges ("50-100") become
  their integer midpoint; unparseable headcount values become `None` (which
  then fails qualification per the fail-closed rule above).

## Full endpoint list (`/api` prefix)

| Method & path | Purpose |
|---|---|
| `POST /api/ingest` | Upload a CSV (`file` form field); ingest + normalize rows. |
| `POST /api/qualify` | Run Stage 2 qualify over all `INGESTED` prospects. |
| `GET /api/prospects?status=` | List prospects, optional status filter. |
| `GET /api/prospects/{id}` | Full prospect detail: prospect, company, research, draft, risk flags, pdf_available. |
| `POST /api/prospects/{id}/research` | Kick off Stage 3 (background task); `202`. |
| `GET /api/prospects/{id}/research/status` | Poll Stage 3 job status. |
| `POST /api/prospects/{id}/synthesize` | Run Stage 4 (single LLM call) if hook_strength >= 2. |
| `POST /api/prospects/{id}/render` | Run Stage 5, store the PDF, return its URL. |
| `GET /api/prospects/{id}/pdf` | Download the rendered PDF. |
| `GET /api/review-queue` | List prospects awaiting a human decision. |
| `POST /api/review-queue/{id}/approve` | Approve. |
| `POST /api/review-queue/{id}/edit` | Edit connection note / email sequence; returns character edit distance. |
| `POST /api/review-queue/{id}/reject` | Reject with a reason. |
| `GET /api/disqualified` | List prospects Stage 3 concluded have no usable hook. |
| `GET /api/eval/metrics` | Best-effort metrics (see above); `null` where under-determined. |
| `POST /api/pipeline/run-batch` | Convenience: qualify + research + synthesize + render, best-effort. |

Also `GET /health` (outside `/api`) for a trivial liveness check.

## Notes on the two non-negotiable rules

- **Citation grounding (Stage 3)**: `app/agent/tools.py::handle_tool_call`
  rejects any `record_finding` call whose `source_url` is not already in the
  session's `fetched_urls` set (populated only by a successful `fetch` call
  in that same run), returning a `tool_result` with `is_error=True` -- never
  raising. See `tests/test_record_finding.py` for isolated coverage,
  including that a fresh `AgentSession` never inherits another run's fetched
  URLs.
- **Deterministic shell, agentic core**: Stages 1, 2, 5, 6, 8 are plain
  Python with no LLM calls anywhere in their code paths. Stage 3 is the only
  looping agent (`app/agent/loop.py`, a hand-rolled `while` loop over
  `client.messages.create` -- no framework). Stage 4
  (`app/stages/stage4_synthesize.py`) makes exactly one non-looping
  `client.messages.create` call with a forced `tool_choice`, and its output
  is validated in plain Python afterward, not trusted.
