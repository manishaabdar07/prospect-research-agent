from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crm import PostgresCRMAdapter
from app.database import get_db
from app.deps import require_llm_configured
from app.models import (
    Company,
    Finding,
    OutreachDraft,
    Prospect,
    ProspectStatus,
    ResearchFindings,
)
from app.risk_flags import compute_risk_flags
from app.schemas import (
    CompanySchema,
    OutreachDraftSchema,
    ProspectDetailResponse,
    ProspectListItem,
    ProspectSchema,
    RenderResponse,
    ResearchFindingsSchema,
    ResearchStartResponse,
    ResearchStatusResponse,
    SynthesizeResponse,
)
from app.stages.stage3_agent import get_job_error, run_research_job
from app.stages.stage4_synthesize import synthesize_prospect
from app.stages.stage5_render import render_prospect_pdf

router = APIRouter(tags=["prospects"])


def _get_prospect_or_404(db: Session, prospect_id: str) -> Prospect:
    prospect = db.get(Prospect, prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="prospect not found")
    return prospect


@router.get("/prospects", response_model=list[ProspectListItem])
def list_prospects(status: ProspectStatus | None = None, db: Session = Depends(get_db)) -> list[ProspectListItem]:
    query = select(Prospect)
    if status is not None:
        query = query.where(Prospect.status == status)
    prospects = db.scalars(query.order_by(Prospect.ingested_at.desc())).all()

    items: list[ProspectListItem] = []
    for p in prospects:
        company = db.get(Company, p.company_id)
        research = db.get(ResearchFindings, p.prospect_id)
        items.append(
            ProspectListItem(
                prospect_id=p.prospect_id,
                full_name=p.full_name,
                title_raw=p.title_raw,
                company_name=company.name if company else "",
                city=company.city if company else "",
                role_bucket=p.role_bucket,
                seniority=p.seniority,
                status=p.status,
                hook_strength=research.hook_strength if research else None,
            )
        )
    return items


@router.get("/prospects/{prospect_id}", response_model=ProspectDetailResponse)
def get_prospect(prospect_id: str, db: Session = Depends(get_db)) -> ProspectDetailResponse:
    prospect = _get_prospect_or_404(db, prospect_id)
    company = db.get(Company, prospect.company_id)
    if company is None:
        raise HTTPException(status_code=500, detail="prospect has no associated company")

    findings = db.scalars(select(Finding).where(Finding.prospect_id == prospect_id)).all()
    research = db.get(ResearchFindings, prospect_id)
    draft = db.get(OutreachDraft, prospect_id)

    research_schema = None
    if research is not None:
        research_schema = ResearchFindingsSchema(
            prospect_id=research.prospect_id,
            findings=findings,
            slots_filled=research.slots_filled,
            slots_empty=research.slots_empty,
            hook_strength=research.hook_strength,
            terminal_reason=research.terminal_reason,
            agent_notes=research.agent_notes,
            tool_calls_used=research.tool_calls_used,
        )

    flags = compute_risk_flags(prospect, company, findings, draft)
    pdf_available = bool(prospect.pdf_path) and Path(prospect.pdf_path).exists()

    draft_schema = OutreachDraftSchema.model_validate(draft) if draft is not None else None

    return ProspectDetailResponse(
        prospect=ProspectSchema.model_validate(prospect),
        company=CompanySchema.model_validate(company),
        research=research_schema,
        draft=draft_schema,
        risk_flags=flags,
        pdf_available=pdf_available,
    )


@router.post("/prospects/{prospect_id}/research", response_model=ResearchStartResponse, status_code=202)
def start_research(
    prospect_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _llm=Depends(require_llm_configured),
) -> ResearchStartResponse:
    _get_prospect_or_404(db, prospect_id)
    background_tasks.add_task(run_research_job, prospect_id)
    return ResearchStartResponse(job_status="RUNNING")


@router.get("/prospects/{prospect_id}/research/status", response_model=ResearchStatusResponse)
def research_status(prospect_id: str, db: Session = Depends(get_db)) -> ResearchStatusResponse:
    prospect = _get_prospect_or_404(db, prospect_id)

    if get_job_error(prospect_id):
        return ResearchStatusResponse(status="ERROR")

    if prospect.status == ProspectStatus.RESEARCHING:
        return ResearchStatusResponse(status="RUNNING")

    research = db.get(ResearchFindings, prospect_id)
    if research is not None:
        return ResearchStatusResponse(
            status="DONE",
            hook_strength=research.hook_strength,
            terminal_reason=research.terminal_reason,
        )

    return ResearchStatusResponse(status="PENDING")


@router.post("/prospects/{prospect_id}/synthesize", response_model=SynthesizeResponse)
def synthesize(
    prospect_id: str,
    db: Session = Depends(get_db),
    _llm=Depends(require_llm_configured),
) -> SynthesizeResponse:
    prospect = _get_prospect_or_404(db, prospect_id)
    research = db.get(ResearchFindings, prospect_id)

    # Hard requirement: hook_strength < 2 must route to DISQUALIFIED and skip
    # Stage 4 entirely BEFORE any LLM call is made.
    if research is None:
        raise HTTPException(status_code=400, detail="prospect has not completed research yet")
    if research.hook_strength < 2:
        prospect.status = ProspectStatus.DISQUALIFIED
        db.commit()
        return SynthesizeResponse(status="DISQUALIFIED", draft=None)

    outcome = synthesize_prospect(db, prospect)
    draft_schema = OutreachDraftSchema.model_validate(outcome.draft) if outcome.draft is not None else None
    return SynthesizeResponse(status=outcome.status, draft=draft_schema)


@router.post("/prospects/{prospect_id}/render", response_model=RenderResponse)
def render(prospect_id: str, db: Session = Depends(get_db)) -> RenderResponse:
    prospect = _get_prospect_or_404(db, prospect_id)
    company = db.get(Company, prospect.company_id)
    if company is None:
        raise HTTPException(status_code=500, detail="prospect has no associated company")

    research = db.get(ResearchFindings, prospect_id)
    if research is None:
        raise HTTPException(status_code=400, detail="prospect has not completed research yet")

    findings = db.scalars(select(Finding).where(Finding.prospect_id == prospect_id)).all()
    draft = db.get(OutreachDraft, prospect_id)
    flags = compute_risk_flags(prospect, company, findings, draft)

    path = render_prospect_pdf(prospect, company, findings, research, draft, flags)

    crm = PostgresCRMAdapter(db)
    crm.attach_file(prospect.prospect_id, path)

    if prospect.status not in (ProspectStatus.APPROVED, ProspectStatus.REJECTED, ProspectStatus.EDITED):
        prospect.status = ProspectStatus.RENDERED
        db.commit()

    return RenderResponse(pdf_url=f"/api/prospects/{prospect_id}/pdf")


@router.get("/prospects/{prospect_id}/pdf")
def get_pdf(prospect_id: str, db: Session = Depends(get_db)) -> Response:
    prospect = _get_prospect_or_404(db, prospect_id)
    if not prospect.pdf_path or not Path(prospect.pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF not available -- call render first")
    return FileResponse(prospect.pdf_path, media_type="application/pdf", filename=f"{prospect_id}.pdf")
