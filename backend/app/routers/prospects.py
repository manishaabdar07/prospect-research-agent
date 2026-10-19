from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_email_configured, require_llm_configured
from app.email_service import EmailSendError, get_email_service
from app.models import (
    Company,
    EmailDraft,
    EmailDraftStatus,
    Finding,
    Prospect,
    ProspectStatus,
    ResearchFindings,
)
from app.risk_flags import compute_risk_flags
from app.schemas import (
    CompanySchema,
    EmailDraftEditRequest,
    EmailDraftSchema,
    EmailGenerateResponse,
    ProspectDetailResponse,
    ProspectListItem,
    ProspectSchema,
    ResearchFindingsSchema,
    ResearchStartResponse,
    ResearchStatusResponse,
    SendEmailResponse,
)
from app.stages.stage3_agent import get_job_error, run_research_job
from app.stages.stage4_generate_email import generate_email as run_generate_email

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
    draft = db.get(EmailDraft, prospect_id)

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
    draft_schema = EmailDraftSchema.model_validate(draft) if draft is not None else None

    return ProspectDetailResponse(
        prospect=ProspectSchema.model_validate(prospect),
        company=CompanySchema.model_validate(company),
        research=research_schema,
        draft=draft_schema,
        risk_flags=flags,
    )


@router.post("/prospects/{prospect_id}/research", response_model=ResearchStartResponse, status_code=202)
def start_research(
    prospect_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _llm=Depends(require_llm_configured),
) -> ResearchStartResponse:
    prospect = _get_prospect_or_404(db, prospect_id)
    # Set immediately, before the background task actually starts running, so
    # a client polling right after this call sees a real "queued" state
    # instead of the job appearing not to have started at all.
    prospect.status = ProspectStatus.RESEARCH_PENDING
    db.commit()
    background_tasks.add_task(run_research_job, prospect_id)
    return ResearchStartResponse(job_status="RUNNING")


@router.get("/prospects/{prospect_id}/research/status", response_model=ResearchStatusResponse)
def research_status(prospect_id: str, db: Session = Depends(get_db)) -> ResearchStatusResponse:
    prospect = _get_prospect_or_404(db, prospect_id)

    if prospect.status == ProspectStatus.ERROR:
        return ResearchStatusResponse(status="ERROR", error_message=prospect.last_error or get_job_error(prospect_id))
    if prospect.status == ProspectStatus.RESEARCH_PENDING:
        return ResearchStatusResponse(status="PENDING")
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


@router.post("/prospects/{prospect_id}/generate-email", response_model=EmailGenerateResponse)
def generate_email(
    prospect_id: str,
    db: Session = Depends(get_db),
    _llm=Depends(require_llm_configured),
) -> EmailGenerateResponse:
    prospect = _get_prospect_or_404(db, prospect_id)
    research = db.get(ResearchFindings, prospect_id)

    # Hard requirement: hook_strength < 2 must route to DISQUALIFIED and skip
    # Stage 4 entirely BEFORE any LLM call is made.
    if research is None:
        raise HTTPException(status_code=400, detail="prospect has not completed research yet")
    if research.hook_strength < 2:
        prospect.status = ProspectStatus.DISQUALIFIED
        db.commit()
        return EmailGenerateResponse(status="DISQUALIFIED", draft=None)

    outcome = run_generate_email(db, prospect)
    draft_schema = EmailDraftSchema.model_validate(outcome.draft) if outcome.draft is not None else None
    return EmailGenerateResponse(status=outcome.status, draft=draft_schema)


@router.patch("/prospects/{prospect_id}/email-draft", response_model=EmailDraftSchema)
def update_email_draft(
    prospect_id: str,
    body: EmailDraftEditRequest,
    db: Session = Depends(get_db),
) -> EmailDraftSchema:
    prospect = _get_prospect_or_404(db, prospect_id)
    draft = db.get(EmailDraft, prospect_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="no email draft for this prospect yet")
    if prospect.status == ProspectStatus.EMAIL_SENT:
        raise HTTPException(status_code=400, detail="cannot edit a draft that has already been sent")

    if body.subject is not None:
        draft.subject = body.subject
    if body.body is not None:
        draft.body = body.body
    db.commit()
    return EmailDraftSchema.model_validate(draft)


@router.post("/prospects/{prospect_id}/send-email", response_model=SendEmailResponse)
def send_email(
    prospect_id: str,
    db: Session = Depends(get_db),
    _email=Depends(require_email_configured),
) -> SendEmailResponse:
    prospect = _get_prospect_or_404(db, prospect_id)

    # Never auto-send, never resend: only a prospect sitting exactly at
    # EMAIL_DRAFTED (a fresh, unsent draft) is eligible.
    if prospect.status != ProspectStatus.EMAIL_DRAFTED:
        raise HTTPException(
            status_code=400,
            detail=f"prospect is not ready to send (status={prospect.status.value}); "
            "either no draft exists yet, or it was already sent",
        )

    draft = db.get(EmailDraft, prospect_id)
    if draft is None or draft.disqualify:
        raise HTTPException(status_code=400, detail="no sendable email draft for this prospect")
    if not prospect.email:
        raise HTTPException(status_code=400, detail="prospect has no recipient email address on file")
    if not draft.subject or not draft.body:
        raise HTTPException(status_code=400, detail="email draft subject/body must not be empty")

    try:
        get_email_service().send(to=prospect.email, subject=draft.subject, body=draft.body)
    except EmailSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = datetime.utcnow()
    draft.status = EmailDraftStatus.SENT
    draft.sent_at = now
    prospect.status = ProspectStatus.EMAIL_SENT
    db.commit()
    return SendEmailResponse(status="SENT", sent_at=now)
