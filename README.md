# Prospect Research Agent

Outbound-prospecting research pipeline (see `Appendix A` spec). Deterministic
shell, one agentic core (Stage 3 research). A human approves and sends every
message manually — this system never sends anything.

Two independent projects:

- `backend/` — Python 3.11+, FastAPI, PostgreSQL (SQLAlchemy + Alembic),
  Anthropic Claude for the Stage 3 tool-use research agent and the Stage 4
  structured synthesis call.
- `frontend/` — React + TypeScript + Vite, talks to the backend's `/api`.

## Local Postgres

```
docker compose up -d
```

Starts Postgres on `localhost:5433` (mapped off the default 5432 to avoid
clashing with any native Postgres already installed on the host), db
`prospect_research`, user/password `prospect`/`prospect`. Matches the
`DATABASE_URL` in `backend/.env.example`:

```
postgresql://prospect:prospect@localhost:5433/prospect_research
```

If you already run Postgres locally, skip this and point `DATABASE_URL` at
your own instance instead.

## Run backend

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then fill in ANTHROPIC_API_KEY etc.
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

See `backend/README.md` for env var details, the WeasyPrint-on-Windows
fallback, and design notes.

## Run frontend

```
cd frontend
npm install
copy .env.example .env.development   # optional, defaults already point at :8000
npm run dev
```

Opens on `http://localhost:5173`, expects the backend running on `:8000`.

See `frontend/README.md` for page-by-page notes.

## Without API keys

The app boots and the deterministic stages (CSV ingest, qualify, review
queue, disqualified queue) work with no external services. Research
(Stage 3) and synthesis (Stage 4) need `ANTHROPIC_API_KEY`; web search
defaults to a `mock` provider until `SEARCH_PROVIDER=brave` and
`BRAVE_API_KEY` are set.
