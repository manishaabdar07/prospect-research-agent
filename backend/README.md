# Prospect Research Agent - Backend

FastAPI backend for Gunadhya's outbound-prospecting research pipeline. CSV
upload is the **only manual step** in the whole workflow: qualify (with a
stored reason for every prospect), the per-prospect LLM research agent, and
single-LLM-call email generation all run automatically, back-to-back, the
moment a CSV is ingested. The one thing that stays manual after that is
sending -- a human reviews/edits the generated draft in the web UI and
explicitly clicks Send (SMTP). Nothing is ever auto-sent.

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
# edit .env if you want a real OpenAI key / Brave key / SMTP credentials / different DB URL

# 4. Start Postgres (via the root docker-compose.yml, or your own instance)
#    Must match backend/.env's DATABASE_URL, default:
#    postgresql://prospect:prospect@localhost:5432/prospect_research

# 5. Run migrations
alembic upgrade head

# 6. Run the app
uvicorn app.main:app --reload --port 8000
```

The app boots with **zero required configuration**: no `OPENAI_API_KEY`
needed to start it, and `SEARCH_PROVIDER=mock` is the default so no search
API key is needed either. `/api/ingest` and `/api/qualify` work immediately.
`/api/prospects/{id}/research` and `/api/prospects/{id}/generate-email` return
a clean `503 {"detail": "LLM not configured, set OPENAI_API_KEY"}` until
you set a real key. `/api/prospects/{id}/send-email` similarly returns a
clean `503` until `EMAIL_HOST`/`EMAIL_FROM` are set.

### Running tests

```powershell
pip install -r requirements.txt   # includes pytest
pytest
```

Tests run against an isolated in-memory SQLite database (see
`tests/conftest.py`), not Postgres, and never call the OpenAI API or the
network -- they exercise Stage 1 ingest parsing, Stage 2 qualify
filtering/reason-tracking, and the `record_finding` citation-validation logic
directly.

## Project layout

```
backend/
  app/
    main.py               FastAPI app, CORS, router wiring
    config.py              Settings (pydantic-settings, reads .env)
    database.py             SQLAlchemy engine/session/Base
    models.py                ORM models (mirrors the spec's data model)
    schemas.py                 Pydantic v2 schemas + API request/response shapes
    deps.py                     shared FastAPI dependencies (LLM/email-configured guards)
    crm.py                       Stage 6 Load: CRMAdapter Protocol + PostgresCRMAdapter
    email_service.py               Stage 6 Send: EmailService Protocol + SMTPEmailService
    llm_client.py                    get_openai_client() -- shared OpenAI client factory
    risk_flags.py                    Stage 8: risk flag computation (read-time)
    search.py                         pluggable search(query) -> list[SearchResult]
    fetch_util.py                      httpx + trafilatura page fetch/extraction
    ids.py                               id/slug helpers
    stages/
      stage1_ingest.py                 Stage 1: CSV -> Company/Prospect (plain code)
      stage2_qualify.py                 Stage 2: filter/dedupe/cap, stores a reason for every prospect
      stage3_agent.py                    Stage 3 glue: run agent loop, persist results
      stage4_generate_email.py            Stage 4: single forced-tool-call LLM email generation
      pipeline_runner.py                    auto qualify->research->generate-email, triggered from /ingest (stops before sending)
    agent/
      tools.py                             Stage 3 tool schemas + handlers
      loop.py                               Stage 3 hand-rolled tool-use while-loop
    routers/                                 one module per endpoint group
  alembic/                                    migrations (versions/0001_initial.py, 0002_email_workflow.py)
  tests/                                        pytest unit tests
  requirements.txt
  .env.example
  Dockerfile
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://prospect:prospect@localhost:5432/prospect_research` | Matches the root `docker-compose.yml` Postgres service credentials exactly. |
| `OPENAI_API_KEY` | unset | Required for `/research` and `/generate-email`. Unset => those endpoints return `503`. |
| `OPENAI_MODEL` | `gpt-4o` | Used for both the Stage 3 agent loop and the Stage 4 single call; must support tool/function calling. |
| `SEARCH_PROVIDER` | `mock` | `mock` (default, no key, always returns `[]`), `duckduckgo` (no key, scrapes DuckDuckGo's HTML results page), or `brave`. |
| `BRAVE_API_KEY` | unset | Only used when `SEARCH_PROVIDER=brave`. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated list; Vite's default dev port. |
| `AGENT_MAX_TOOL_CALLS` | `12` | Stage 3 tool-call budget. |
| `AGENT_WALL_CLOCK_SECONDS` | `90` | Stage 3 wall-clock budget. |
| `AGENT_MAX_CONSECUTIVE_ERRORS` | `2` | Stage 3 consecutive-tool-error stop condition. |
| `QUALIFY_BATCH_CAP` | `20` | Stage 2 hard cap per qualify run (true short-circuit -- see below). |
| `QUALIFY_HEADCOUNT_MIN` / `QUALIFY_HEADCOUNT_MAX` | `10` / `200` | Stage 2 headcount band. |
| `FETCH_TIMEOUT_SECONDS` | `15.0` | httpx timeout for the `fetch` tool. |
| `FETCH_MAX_CHARS` | `16000` | ~4000 tokens, per spec. |
| `EMAIL_PROVIDER` | `smtp` | Only `smtp` is implemented in v1 (generic `smtplib`, no third-party provider SDK). |
| `EMAIL_HOST` / `EMAIL_PORT` | unset / `587` | SMTP server. Port `465` uses implicit TLS (`SMTP_SSL`); anything else uses `STARTTLS`. |
| `EMAIL_USERNAME` / `EMAIL_PASSWORD` | unset | SMTP auth; skipped if either is blank (e.g. a local debug SMTP sink). |
| `EMAIL_FROM` | unset | Envelope/header From address. Required (with `EMAIL_HOST`) for `/send-email`; unset => `503`. |

For safe manual testing of `/send-email` without risking a real inbox, use a
free [Mailtrap.io](https://mailtrap.io) sandbox SMTP inbox, or run a local
debug SMTP sink (`python -m aiosmtpd -n -l localhost:1025`, no auth/TLS, mail
prints to that process's console) with `EMAIL_HOST=localhost`, `EMAIL_PORT=1025`.

## Judgment calls / deviations from the spec

- **Unknown headcount is fail-closed.** A company with no headcount data does
  NOT auto-pass Stage 2 qualification (`app/stages/stage2_qualify.py`). The
  spec's qualification criterion is a headcount band; silently passing
  unknowns would let arbitrarily sized companies into the batch. Revisit
  once a headcount-enrichment step exists.
- **Every Stage-2-evaluated prospect gets a reason, pass or fail.**
  `Prospect.qualification_reason`/`qualified_at` are set for every candidate
  Stage 2 actually looks at -- a failing prospect is moved straight to
  `DISQUALIFIED` with a specific reason (headcount out of range/unknown, city
  not in the Pune-metro allowlist, exclusion-list match, duplicate), rather
  than being left at `INGESTED` with no explanation. The batch cap (`20`) is
  a true short-circuit: once that many prospects have been evaluated and
  qualified, everything else in the queue is left completely untouched
  (`INGESTED`, `qualification_reason=None`) for the next run -- so
  `queued_remaining` means "not yet evaluated," not "evaluated and passed but
  didn't fit."
- **ResearchFindings / EmailDraft are 1:1 with a Prospect, replace-on-rerun.**
  The spec's data model doesn't include a `research_run_id` anywhere, so a
  new Stage 3 run deletes and replaces the prior `Finding`/`ResearchFindings`
  rows for that prospect, and a new Stage 4 run replaces the prior
  `EmailDraft` row. Only the latest run is retained. If run history is wanted
  later, add a `research_run_id` column and stop deleting.
- **RiskFlag is not a table.** Flags are computed at **read time** in
  `app/risk_flags.py` from `Finding`/`EmailDraft` rows already in the DB
  (called from `GET /api/prospects/{id}`). This avoids a persisted flag ever
  disagreeing with the underlying data after an edit, and is cheap given the
  small per-prospect finding count.
- **CRM = Postgres (Stage 6 Load).** The spec suggests SQLite for the CRM
  adapter's own storage, but the whole system already runs on Postgres, so
  `PostgresCRMAdapter` (`app/crm.py`) just upserts into the same
  `companies`/`prospects` tables and writes a `crm_tasks` table. This **is**
  the CRM for v1; the `CRMAdapter` Protocol is kept exactly as specified so a
  real external adapter can be substituted later without touching calling
  code.
- **Email sending is generic SMTP only (Stage 6 Send).** `app/email_service.py`
  defines an `EmailService` Protocol (so a real provider SDK can be dropped
  in later without touching calling code) with one implementation,
  `SMTPEmailService`, using the stdlib `smtplib`/`email.mime.text`. Credentials
  come only from `Settings` (env vars), never hardcoded. Sending is
  **synchronous** -- unlike Stage 3's background-task/polling pattern, a
  single SMTP send is fast enough to complete within the request, so the user
  gets immediate success/failure feedback from clicking Send.
- **Sending is never automatic.** `/api/pipeline/run-batch` and
  `pipeline_runner.py` stop after Stage 4 (email generation) -- only the
  explicit, user-triggered `POST /prospects/{id}/send-email` call ever sends.
  That endpoint also refuses to run unless `Prospect.status == EMAIL_DRAFTED`
  exactly, which blocks both sending before a draft exists and resending
  after one has already gone out (no resend mechanism is implemented).
- **Dedupe order** (Stage 2): `linkedin_url` first, then `(full_name,
  company_id)` fallback, checked only against prospects that have already
  left `INGESTED` in a prior run -- so two rows for the same person within
  the *same* CSV upload don't spuriously dedupe against each other before
  either has been evaluated.
- **`ProspectStatus.ERROR` vs `DISQUALIFIED`**: `ERROR` is reserved for a hard
  system failure in a background job (Stage 3 research or Stage 4 email
  generation raising/crashing) -- persisted to `Prospect.last_error`/
  `last_error_at` so it survives a restart. `DISQUALIFIED` is reserved for
  legitimate business-rule outcomes (failed qualification, weak/no hook,
  or the email-generation model itself judging the findings too thin). These
  used to be conflated (a crash forced `DISQUALIFIED` with a synthetic note);
  they're now distinct so a human knows whether to retry or move on.
- **Stage 4 second-failure handling**: if the forced `return_email` tool call
  still fails validation after one retry, the draft is persisted anyway
  (with `claims_used` filtered down to only ids that actually exist, so the
  citation-grounding rule is never violated even in the fallback path),
  flagged `needs_human_review=True`, and `/generate-email` returns
  `{"status": "NEEDS_REVIEW", "draft": {...}}` rather than silently dropping
  the prospect. A **hard** failure (the LLM call itself raises, or the
  model never returns usable content at all) is different -- that's a system
  error, not "there's a draft worth reviewing," so it routes to
  `ProspectStatus.ERROR` with no `EmailDraft` persisted at all.
- **Upload is the only manual step.** `POST /api/ingest` calls
  `app/stages/pipeline_runner.py::qualify_and_launch_pipeline()` right after
  ingesting, which loops `qualify_batch()` past its own per-call `batch_cap`
  until every ingested prospect has been evaluated (not just the first
  chunk), then schedules `run_full_pipeline_for_prospect` (Stage 3 ->
  Stage 4) as one `BackgroundTasks` job per prospect that qualified.
  `POST /api/pipeline/run-batch` and `POST /api/qualify` still exist and
  still work exactly as before, but are no longer wired to any UI button --
  they're kept as manual/API-level tools (e.g. to re-sweep after manually
  fixing an exclusion-list entry).
- **A missing `OPENAI_API_KEY` is a visible `ERROR`, not a silent dead end.**
  Since there's no manual "Research" button left in the normal flow to retry
  from later, `run_full_pipeline_for_prospect()` marks a prospect
  `ProspectStatus.ERROR` (with `last_error` explaining why) instead of
  silently leaving it at `QUALIFIED` when the key isn't configured. The one
  manual affordance kept anywhere in the UI is a "Retry research" button
  that appears only for `ERROR` prospects -- configure the key, click it
  once, and the automatic chain picks back up from there.
- **Research job status** (`GET /api/prospects/{id}/research/status`) is
  derived primarily from `Prospect.status`/`last_error` in the DB -- those
  are persisted and survive a restart / work across worker processes. A
  small in-memory `dict[prospect_id, str]` (`stage3_agent._job_errors`) is
  kept only as a redundant fast-path for an exception escaping the
  background task wrapper itself; it is per-process and resets on restart,
  which is fine since it's no longer the primary signal.
- **Eval metrics best-effort**: `hook_recall` is a *proxy* (fraction of
  researched prospects with `hook_strength >= 2`), since true recall needs a
  labeled ground-truth set this system doesn't collect.
  `disqualification_precision` is always `null` in v1 -- there's no human
  label to check the system's disqualification decision against.
  `citation_validity` is computed for real from stored `EmailDraft` rows and
  is `null` only when no data exists yet.
- **City/headcount normalization is intentionally simple** (Stage 1):
  city normalization is a casing/whitespace lookup for a fixed list of
  Pune-area spellings, not a geocoder; headcount ranges ("50-100") become
  their integer midpoint; unparseable headcount values become `None` (which
  then fails qualification per the fail-closed rule above).

## Full endpoint list (`/api` prefix)

| Method & path | Purpose |
|---|---|
| `POST /api/ingest` | Upload a CSV (`file` form field); ingest + normalize rows. **The only manual step**: automatically loops Stage 2 qualify over the whole upload, then schedules Stage 3 + Stage 4 (research, then generate-email) as a background job for every prospect that qualified -- see `app/stages/pipeline_runner.py::qualify_and_launch_pipeline`. |
| `GET /api/prospects?status=` | List prospects, optional status filter. |
| `GET /api/prospects/{id}` | Full prospect detail: prospect, company, research, draft, risk flags. |
| `POST /api/prospects/{id}/research` | Manual/recovery only now (e.g. retrying a prospect stuck at `ERROR`) -- normal-path research is kicked off automatically by `/ingest`. Background task; `202`, status flips to `RESEARCH_PENDING` immediately. |
| `GET /api/prospects/{id}/research/status` | Poll Stage 3 job status. |
| `POST /api/prospects/{id}/generate-email` | Manual/recovery only now -- normal-path email generation is kicked off automatically after research completes. Runs Stage 4 (single LLM call) if hook_strength >= 2. |
| `PATCH /api/prospects/{id}/email-draft` | Edit the draft's subject/body before sending. |
| `POST /api/prospects/{id}/send-email` | Send via SMTP; only valid when status is exactly `EMAIL_DRAFTED`. The one step that stays manual by design. |
| `GET /api/disqualified` | List disqualified prospects, tagged with which stage dropped them (`QUALIFICATION`/`RESEARCH`/`EMAIL_GENERATION`). |
| `GET /api/eval/metrics` | Best-effort metrics (see above); `null` where under-determined. |
| `POST /api/qualify` | Manual/admin only now -- kept for API-level re-processing; not exposed via a UI button. |
| `POST /api/pipeline/run-batch` | Manual/admin only now -- same qualify+research+generate-email chain `/ingest` already triggers automatically, kept as a standalone re-sweep tool; not exposed via a UI button. Never sends. |

Also `GET /health` (outside `/api`) for a trivial liveness check.

## Notes on the two non-negotiable rules

- **Citation grounding (Stage 3 & 4)**: `app/agent/tools.py::handle_tool_call`
  rejects any `record_finding` call whose `source_url` is not already in the
  session's `fetched_urls` set (populated only by a successful `fetch` call
  in that same run), returning a `tool_result` with `is_error=True` -- never
  raising. See `tests/test_record_finding.py` for isolated coverage,
  including that a fresh `AgentSession` never inherits another run's fetched
  URLs. Stage 4 (`app/stages/stage4_generate_email.py`) carries the same
  discipline forward into the email itself: every claim must trace to a real
  `finding_id` in `claims_used`, checked in plain Python after the LLM call.
- **Sending is always a separate, explicit, human-triggered action.**
  `POST /prospects/{id}/send-email` is the only code path anywhere in this
  backend that actually transmits an email; nothing else -- not research, not
  email generation, not the batch pipeline convenience endpoint -- ever calls
  it automatically.
- **Deterministic shell, agentic core**: Stages 1, 2, 6, 8 are plain Python
  with no LLM calls anywhere in their code paths. Stage 3 is the only looping
  agent (`app/agent/loop.py`, a hand-rolled `while` loop over
  `client.chat.completions.create` -- no framework). Stage 4
  (`app/stages/stage4_generate_email.py`) makes exactly one non-looping
  `client.chat.completions.create` call with a forced `tool_choice`, and its
  output is validated in plain Python afterward, not trusted.
