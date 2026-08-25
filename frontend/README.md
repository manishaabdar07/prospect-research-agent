# Prospect Research Agent — Frontend

A React + TypeScript + Vite frontend for the Prospect Research Agent: an
outbound-prospecting research pipeline for Gunadhya's B2B sales to
Pune-area manufacturers. This app is the human-facing control surface for
the pipeline (ingest a CSV, run qualification/research/synthesis, review
findings, and approve/edit/reject drafts). **It never sends anything on its
own** — every outbound email is written by the agent, reviewed by a human
in the Review Queue, and sent manually from the reviewer's own email or
LinkedIn.

## Stack

- Vite + React 18 + TypeScript
- Tailwind CSS (utility-first styling)
- React Router v6 (client-side routing across 5 pages)
- TanStack React Query v5 for server state (list/detail caching, mutations,
  and polling research-job status)
- A small hand-written fetch-based API client (`src/api/client.ts`) — no
  axios dependency needed for this surface area

## Requirements

- Node.js 18+ and npm on PATH
- The backend running locally on `http://localhost:8000` (see
  `../backend`), or `VITE_API_BASE_URL` pointed at wherever it runs

## Setup

```powershell
cd frontend
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` by default and reads the
API base URL from `.env.development` (already checked in with a sane
default of `http://localhost:8000/api`). Copy `.env.example` to `.env.local`
if you need to point at a different backend without touching the tracked
default.

## Build

```powershell
npm run build
```

Runs `tsc -b` (project references, strict mode) followed by `vite build`.
The build is verified to complete with zero TypeScript errors as part of
building this project — see "Verification" below.

## Pages

| Route              | Purpose                                                                 |
| ------------------ | ------------------------------------------------------------------------ |
| `/`                 | Dashboard: CSV ingest, run-qualify, run-full-batch, status counts, eval metrics sidebar |
| `/prospects`        | Prospect list with status filter and per-row Research/Synthesize/Render actions |
| `/prospects/:id`    | Prospect detail: company/prospect info, findings table (grouped by evidence slot), risk flags, draft connection note + email sequence, PDF download |
| `/review-queue`     | Human review queue: PDF preview, Approve / Edit (inline note + email editor) / Reject |
| `/disqualified`     | Disqualified prospects, framed as an expected/healthy outcome, not a failure |

## Judgment calls / deviations from the spec

These are places the spec left an implementation detail open, or where I
made a reasonable default rather than asking:

1. **Research status polling** is implemented as a bounded client-side poll
   loop (every 2s, up to 60 attempts ≈ 2 minutes) triggered right after
   `POST /prospects/{id}/research` succeeds, rather than a persistent
   background poller. This keeps the polling logic co-located with the
   button that started the job (both in the Prospects list row and on the
   Prospect Detail page) without a global job-tracking store. If a job runs
   longer than ~2 minutes, the button becomes usable again and the status
   badge on next list refresh will still reflect `RESEARCHING`/`RESEARCHED`
   correctly — the user can just revisit the page.

2. **Editing a review-queue draft**: `GET /review-queue` does not return the
   connection note or email sequence to edit (per the contract it only
   returns `{prospect_id, full_name, company_name, hook_strength, pdf_url,
   risk_flags}`), so the Edit form lazily fetches `GET /prospects/{id}` to
   pre-fill the textarea/email editors with the current draft, then submits
   only the edited fields to `POST /review-queue/{id}/edit`.

3. **PDF preview** in the Review Queue uses a plain `<iframe src={pdf_url}>`
   plus an "Open PDF" link, per the spec's explicit suggestion not to
   over-engineer a PDF viewer. Browsers without native inline PDF rendering
   will show a blank frame; the "Open PDF" link always works.

4. **`company` and `prospect` objects** in `GET /prospects/{id}` are typed
   permissively (`[key: string]: unknown` on top of the documented fields)
   since the contract doesn't fully enumerate every field on those two
   objects. The UI only renders fields it knows about and guards each with
   an existence check, so extra/missing backend fields won't break
   rendering.

5. **LinkedIn URLs are rendered as plain external links only** — never
   fetched, embedded, or previewed by the frontend, per the spec.

6. **Hook strength badge** always shows the 0–3 numeric score plus the
   rubric label (No basis / Generic / Specific hook / Strong hook); a
   compact variant (number only) is used in dense table rows.

7. **Status summary on the Dashboard** is derived client-side by grouping
   the full `GET /prospects` list by `status`, exactly as the spec allows
   ("no new endpoint needed"). For large prospect volumes this could later
   move server-side, but it's fine at the ~20-prospect batch scale this
   system operates at.

8. **Eval metrics widget** is included on the Dashboard sidebar as the spec
   marked it optional-but-nice. Null fields render as "not enough data
   yet" rather than 0% or a blank, so it can't be misread as a real zero
   score.

9. **No auth, no global toast/notification system** — errors and
   confirmations are rendered inline near the action that triggered them,
   consistent with "single-user internal tool" framing in the spec.

## Environment variables

| Variable              | Default                        | Notes                                   |
| ---------------------- | ------------------------------- | ---------------------------------------- |
| `VITE_API_BASE_URL`    | `http://localhost:8000/api`     | Set in `.env.example` and `.env.development`; override via `.env.local` (gitignored) |

## Project layout

```
frontend/
  src/
    api/
      types.ts    # TS types matching the backend API contract field-for-field
      client.ts   # typed fetch wrappers, one function per endpoint
    components/    # StatusBadge, HookStrengthBadge, RiskFlagBadge, FindingsTable,
                    # EmailStepEditor, NavBar, Feedback (Spinner/ErrorBanner/EmptyState)
    pages/          # Dashboard, ProspectsList, ProspectDetail, ReviewQueue, Disqualified
    App.tsx         # route table
    main.tsx        # React Query + Router providers, app entry point
```
