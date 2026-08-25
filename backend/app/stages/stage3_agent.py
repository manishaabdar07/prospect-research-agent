"""Stage 3 glue: runs the Stage 3 agent loop for one prospect and persists results.

Run as a FastAPI BackgroundTasks job (see app/routers/research.py). Status is
derived primarily from Prospect.status in the DB; `_job_errors` only tracks
the rare case of an unhandled exception escaping the background task wrapper
itself (run_research_agent is designed to never raise, but this is a last
line of defense so a crash never leaves a prospect stuck at RESEARCHING
forever without any signal).
"""
from __future__ import annotations

from sqlalchemy import delete

from app.agent.loop import run_research_agent
from app.database import SessionLocal
from app.models import Company, Finding, FindingSlot, Prospect, ProspectStatus, ResearchFindings, TerminalReason

ALL_SLOTS = [s.value for s in FindingSlot]

# prospect_id -> error message, for background-task-level crashes only.
_job_errors: dict[str, str] = {}


def get_job_error(prospect_id: str) -> str | None:
    return _job_errors.get(prospect_id)


def clear_job_error(prospect_id: str) -> None:
    _job_errors.pop(prospect_id, None)


def run_research_job(prospect_id: str) -> None:
    """Entry point for BackgroundTasks. Opens its own DB session."""
    clear_job_error(prospect_id)
    db = SessionLocal()
    try:
        prospect = db.get(Prospect, prospect_id)
        if prospect is None:
            _job_errors[prospect_id] = "prospect not found"
            return

        prospect.status = ProspectStatus.RESEARCHING
        db.commit()

        company = db.get(Company, prospect.company_id)
        if company is None:
            _job_errors[prospect_id] = "company not found"
            return

        result = run_research_agent(prospect, company)

        # Replace any prior run's findings for this prospect (see models.py
        # docstring: only the latest research run is retained).
        db.execute(delete(Finding).where(Finding.prospect_id == prospect_id))
        existing_rf = db.get(ResearchFindings, prospect_id)
        if existing_rf is not None:
            db.delete(existing_rf)
        db.flush()

        filled_slots = sorted({f.slot for f in result.findings})
        empty_slots = [s for s in ALL_SLOTS if s not in filled_slots]

        for f in result.findings:
            db.add(
                Finding(
                    finding_id=f.finding_id,
                    prospect_id=prospect_id,
                    slot=FindingSlot(f.slot),
                    claim=f.claim,
                    source_url=f.source_url,
                    retrieved_at=f.retrieved_at,
                    confidence=f.confidence,
                )
            )

        db.add(
            ResearchFindings(
                prospect_id=prospect_id,
                slots_filled=filled_slots,
                slots_empty=empty_slots,
                hook_strength=result.hook_strength,
                terminal_reason=TerminalReason(result.terminal_reason),
                agent_notes=result.agent_notes,
                tool_calls_used=result.tool_calls_used,
            )
        )

        # "No hook found" (hook_strength < 2) is a first-class outcome: route
        # straight to DISQUALIFIED and skip Stage 4 entirely.
        if result.hook_strength >= 2:
            prospect.status = ProspectStatus.RESEARCHED
        else:
            prospect.status = ProspectStatus.DISQUALIFIED

        db.commit()
    except Exception as exc:  # last line of defense; run_research_agent should already catch its own errors
        db.rollback()
        _job_errors[prospect_id] = str(exc)
        prospect = db.get(Prospect, prospect_id)
        if prospect is not None:
            # Leave a trace rather than an unexplained stuck RESEARCHING status.
            prospect.status = ProspectStatus.DISQUALIFIED
            db.add(
                ResearchFindings(
                    prospect_id=prospect_id,
                    slots_filled=[],
                    slots_empty=ALL_SLOTS,
                    hook_strength=0,
                    terminal_reason=TerminalReason.ERROR,
                    agent_notes=f"Background job crashed: {exc}",
                    tool_calls_used=0,
                )
            )
            db.commit()
    finally:
        db.close()
