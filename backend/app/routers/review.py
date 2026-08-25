"""Review queue endpoints (human-in-the-loop terminal state).

A prospect appears in the review queue once it has a non-disqualifying draft
and has NOT yet received a terminal review decision (approve/edit/reject).
pdf_url is included only once the PDF has actually been rendered.
"""
from __future__ import annotations

import difflib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    Finding,
    OutreachDraft,
    Prospect,
    ProspectStatus,
    ReviewAction,
    ReviewActionType,
)
from app.risk_flags import compute_risk_flags
from app.schemas import (
    ApproveResponse,
    EditRequest,
    EditResponse,
    RejectRequest,
    RejectResponse,
    ReviewQueueItem,
)

router = APIRouter(tags=["review"])

REVIEWABLE_STATUSES = {ProspectStatus.SYNTHESIZED, ProspectStatus.RENDERED}


def _get_reviewable_prospect(db: Session, prospect_id: str) -> Prospect:
    prospect = db.get(Prospect, prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="prospect not found")
    return prospect


def _char_edit_distance(a: str, b: str) -> int:
    """Character-level diff length via difflib -- counts of non-'equal' opcodes."""
    matcher = difflib.SequenceMatcher(None, a or "", b or "")
    distance = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        distance += max(i2 - i1, j2 - j1)
    return distance


@router.get("/review-queue", response_model=list[ReviewQueueItem])
def review_queue(db: Session = Depends(get_db)) -> list[ReviewQueueItem]:
    prospects = db.scalars(
        select(Prospect).where(Prospect.status.in_(REVIEWABLE_STATUSES)).order_by(Prospect.ingested_at.asc())
    ).all()

    items: list[ReviewQueueItem] = []
    for p in prospects:
        draft = db.get(OutreachDraft, p.prospect_id)
        if draft is None or draft.disqualify:
            continue
        company = db.get(Company, p.company_id)
        findings = db.scalars(select(Finding).where(Finding.prospect_id == p.prospect_id)).all()
        flags = compute_risk_flags(p, company, findings, draft)
        from app.models import ResearchFindings

        research = db.get(ResearchFindings, p.prospect_id)
        pdf_url = f"/api/prospects/{p.prospect_id}/pdf" if p.pdf_path else None
        items.append(
            ReviewQueueItem(
                prospect_id=p.prospect_id,
                full_name=p.full_name,
                company_name=company.name if company else "",
                hook_strength=research.hook_strength if research else None,
                pdf_url=pdf_url,
                risk_flags=flags,
            )
        )
    return items


@router.post("/review-queue/{prospect_id}/approve", response_model=ApproveResponse)
def approve(prospect_id: str, db: Session = Depends(get_db)) -> ApproveResponse:
    prospect = _get_reviewable_prospect(db, prospect_id)
    prospect.status = ProspectStatus.APPROVED
    db.add(ReviewAction(prospect_id=prospect_id, action=ReviewActionType.APPROVE))
    db.commit()
    return ApproveResponse(status="APPROVED")


@router.post("/review-queue/{prospect_id}/edit", response_model=EditResponse)
def edit(prospect_id: str, body: EditRequest, db: Session = Depends(get_db)) -> EditResponse:
    prospect = _get_reviewable_prospect(db, prospect_id)
    draft = db.get(OutreachDraft, prospect_id)
    if draft is None:
        raise HTTPException(status_code=400, detail="prospect has no draft to edit")

    original_text = draft.connection_note + "\n" + "\n".join(
        f"{s.get('subject', '')}\n{s.get('body', '')}" for s in (draft.email_sequence or [])
    )

    new_note = body.edited_connection_note if body.edited_connection_note is not None else draft.connection_note
    new_sequence = (
        [step.model_dump() for step in body.edited_email_sequence]
        if body.edited_email_sequence is not None
        else draft.email_sequence
    )
    new_text = new_note + "\n" + "\n".join(f"{s.get('subject', '')}\n{s.get('body', '')}" for s in (new_sequence or []))

    edit_distance = _char_edit_distance(original_text, new_text)

    db.add(
        ReviewAction(
            prospect_id=prospect_id,
            action=ReviewActionType.EDIT,
            edited_connection_note=body.edited_connection_note,
            edited_email_sequence=[s.model_dump() for s in body.edited_email_sequence] if body.edited_email_sequence else None,
            edit_distance=edit_distance,
        )
    )

    # Apply the edit to the live draft so future renders/PDFs reflect it.
    draft.connection_note = new_note
    draft.email_sequence = new_sequence
    prospect.status = ProspectStatus.EDITED
    db.commit()

    return EditResponse(status="EDITED", edit_distance=edit_distance)


@router.post("/review-queue/{prospect_id}/reject", response_model=RejectResponse)
def reject(prospect_id: str, body: RejectRequest, db: Session = Depends(get_db)) -> RejectResponse:
    prospect = _get_reviewable_prospect(db, prospect_id)
    prospect.status = ProspectStatus.REJECTED
    db.add(ReviewAction(prospect_id=prospect_id, action=ReviewActionType.REJECT, reject_reason=body.reason))
    db.commit()
    return RejectResponse(status="REJECTED")
