"""Best-effort convenience orchestration for POST /api/pipeline/run-batch.

Chains Stage 3 (research) -> Stage 4 (synthesize) -> Stage 5 (render) for one
prospect, each stage opening its own short-lived DB session so a crash partway
through never leaves the process holding a stale/half-committed session.
Called once per newly-qualified prospect_id, each as its own BackgroundTasks
job, so prospects in a batch run concurrently-ish (FastAPI runs background
tasks sequentially on the same worker by default, but each is independent
and a failure in one does not affect the others).
"""
from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.crm import PostgresCRMAdapter
from app.database import SessionLocal
from app.models import Company, Finding, OutreachDraft, Prospect, ProspectStatus, ResearchFindings
from app.risk_flags import compute_risk_flags
from app.stages.stage3_agent import run_research_job
from app.stages.stage4_synthesize import synthesize_prospect
from app.stages.stage5_render import render_prospect_pdf


def run_full_pipeline_for_prospect(prospect_id: str) -> None:
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        # Stage 3/4 need the LLM; nothing more we can do for this prospect
        # in this batch run. It stays at QUALIFIED for a manual retry later.
        return

    run_research_job(prospect_id)  # commits its own status transitions

    db = SessionLocal()
    try:
        prospect = db.get(Prospect, prospect_id)
        if prospect is None or prospect.status != ProspectStatus.RESEARCHED:
            return  # DISQUALIFIED (no hook) or ERROR -- nothing further to do

        outcome = synthesize_prospect(db, prospect)
        if outcome.status != "DONE":
            return  # DISQUALIFIED at synthesis, or flagged ERROR for human review

        company = db.get(Company, prospect.company_id)
        findings = db.scalars(select(Finding).where(Finding.prospect_id == prospect_id)).all()
        research = db.get(ResearchFindings, prospect_id)
        draft = db.get(OutreachDraft, prospect_id)
        flags = compute_risk_flags(prospect, company, findings, draft)

        path = render_prospect_pdf(prospect, company, findings, research, draft, flags)
        crm = PostgresCRMAdapter(db)
        crm.attach_file(prospect.prospect_id, path)

        prospect.status = ProspectStatus.RENDERED
        db.commit()
    finally:
        db.close()
