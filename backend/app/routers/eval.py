"""Best-effort evaluation metrics computed from stored data.

Every metric returns null (None) when there isn't enough underlying data to
compute it meaningfully -- this endpoint never fabricates a number. See the
README's "Eval metrics" section for exactly what each metric measures and
why some of them stay null in a fresh install.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Finding, OutreachDraft, ProspectStatus, ResearchFindings, ReviewAction, ReviewActionType
from app.schemas import EvalMetricsResponse

router = APIRouter(tags=["eval"])


@router.get("/eval/metrics", response_model=EvalMetricsResponse)
def eval_metrics(db: Session = Depends(get_db)) -> EvalMetricsResponse:
    research_rows = db.scalars(select(ResearchFindings)).all()

    # hook_recall: proxy metric -- of prospects that completed research, what
    # fraction produced a usable hook (hook_strength >= 2)? True recall would
    # need a labeled ground-truth set of "should have had a hook" prospects,
    # which this system doesn't collect, so this is documented as a proxy.
    hook_recall = None
    if research_rows:
        with_hook = sum(1 for r in research_rows if r.hook_strength >= 2)
        hook_recall = with_hook / len(research_rows)

    # disqualification_precision: would require human-labeled ground truth on
    # DISQUALIFIED prospects (they never reach the review queue in this
    # system, so there's no ReviewAction to compare against). Always null
    # until such a labeling mechanism exists.
    disqualification_precision = None

    # citation_validity: fraction of claims_used ids, across all drafts, that
    # actually exist among that prospect's Finding rows. Should be ~1.0 given
    # Stage 4's own validation, but computed from real data rather than assumed.
    drafts = db.scalars(select(OutreachDraft)).all()
    citation_validity = None
    total_claims = 0
    valid_claims = 0
    for d in drafts:
        if not d.claims_used:
            continue
        finding_ids = {
            f.finding_id for f in db.scalars(select(Finding).where(Finding.prospect_id == d.prospect_id)).all()
        }
        for claim_id in d.claims_used:
            total_claims += 1
            if claim_id in finding_ids:
                valid_claims += 1
    if total_claims > 0:
        citation_validity = valid_claims / total_claims

    # avg_edit_distance: average character-level edit distance across all
    # EDIT review actions logged so far.
    edit_actions = db.scalars(
        select(ReviewAction).where(ReviewAction.action == ReviewActionType.EDIT, ReviewAction.edit_distance.is_not(None))
    ).all()
    avg_edit_distance = None
    if edit_actions:
        avg_edit_distance = sum(a.edit_distance for a in edit_actions) / len(edit_actions)

    return EvalMetricsResponse(
        hook_recall=hook_recall,
        disqualification_precision=disqualification_precision,
        citation_validity=citation_validity,
        avg_edit_distance=avg_edit_distance,
    )
