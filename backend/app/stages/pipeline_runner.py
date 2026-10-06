"""Pipeline orchestration: automatic qualify -> research -> generate-email.

Two entry points:
  - qualify_and_launch_pipeline(): called from POST /api/ingest so upload is
    the only manual step in the whole workflow. Loops Stage 2 qualify until
    every ingested prospect has been evaluated (qualify_batch's batch_cap is
    just a per-call chunk size, not a permanent stopping point here), then
    schedules run_full_pipeline_for_prospect as a BackgroundTasks job for
    every prospect that qualified.
  - run_full_pipeline_for_prospect(): chains Stage 3 (research) -> Stage 4
    (generate email) for one prospect, each stage opening its own
    short-lived DB session so a crash partway through never leaves the
    process holding a stale/half-committed session. Also the function POST
    /api/pipeline/run-batch schedules per newly-qualified prospect_id (that
    endpoint is unchanged, kept as a manual/API-level recovery tool).

Deliberately stops after email generation -- sending must only ever happen
from the explicit user-triggered POST /prospects/{id}/send-email endpoint,
never automatically from any batch/ingest convenience path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Prospect, ProspectStatus
from app.stages.stage2_qualify import qualify_batch
from app.stages.stage3_agent import run_research_job
from app.stages.stage4_generate_email import generate_email

# Defensive upper bound on qualify loop iterations -- each iteration strictly
# drains the INGESTED pool (qualify_batch always moves evaluated candidates
# to QUALIFIED/DISQUALIFIED), so this should never actually be hit; it just
# prevents a pathological infinite loop from ever hanging a request.
_MAX_QUALIFY_ITERATIONS = 200


@dataclass
class AutoPipelineResult:
    qualified_ids: list[str] = field(default_factory=list)
    disqualified_count: int = 0


def qualify_and_launch_pipeline(
    db: Session,
    background_tasks: BackgroundTasks,
    *,
    batch_cap: int,
) -> AutoPipelineResult:
    """Qualify every currently-INGESTED prospect (looping past the per-call
    batch cap so a whole upload gets processed, not just the first chunk),
    then kick off research+generate-email in the background for each one
    that qualified."""
    result = AutoPipelineResult()

    for _ in range(_MAX_QUALIFY_ITERATIONS):
        batch = qualify_batch(db, batch_cap=batch_cap)
        result.qualified_ids.extend(batch.qualified_ids)
        result.disqualified_count += batch.disqualified_count
        if batch.queued_remaining == 0:
            break

    for prospect_id in result.qualified_ids:
        background_tasks.add_task(run_full_pipeline_for_prospect, prospect_id)

    return result


def run_full_pipeline_for_prospect(prospect_id: str) -> None:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        # No manual "Research" button exists in the primary flow to retry
        # from once a key is later configured -- leaving this prospect at
        # QUALIFIED would silently strand it forever. Surface it as a real,
        # visible, recoverable ERROR instead (the one manual affordance kept
        # for exactly this case: retry-on-ERROR).
        db = SessionLocal()
        try:
            prospect = db.get(Prospect, prospect_id)
            if prospect is not None:
                prospect.status = ProspectStatus.ERROR
                prospect.last_error = "OPENAI_API_KEY is not configured -- set it, then retry research."
                prospect.last_error_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        return

    run_research_job(prospect_id)  # commits its own status transitions

    db = SessionLocal()
    try:
        prospect = db.get(Prospect, prospect_id)
        if prospect is None or prospect.status != ProspectStatus.RESEARCH_COMPLETED:
            return  # DISQUALIFIED (no hook) or ERROR -- nothing further to do

        generate_email(db, prospect)  # commits its own status transitions
    finally:
        db.close()
