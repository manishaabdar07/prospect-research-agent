"""Stage 2 - Qualify: orchestration only. Rule evaluation lives in
app/stages/qualification_engine.py, driven by a DB-configured
QualificationCampaign's criteria instead of hardcoded values (see that
module's docstring for the rationale and the field allowlist that keeps
DB-driven config from becoming arbitrary code execution).

Multiple campaigns can be saved; exactly one is "active" at a time and is
what the automatic post-ingest pipeline always qualifies against (see
app/stages/pipeline_runner.py). A specific campaign_id can also be passed
for a one-off `POST /api/qualify` call without changing which one is active.

Judgment calls that still apply (see README for the full list):
- Batch cap is a hard limit (default 20, configurable via QUALIFY_BATCH_CAP),
  enforced as a true short-circuit: once that many prospects have been
  evaluated and qualified, the rest of the INGESTED queue is left completely
  untouched (status stays INGESTED, qualification_reason stays None) for the
  next qualify run, rather than being evaluated now and discarded.
  "queued_remaining" therefore means "not yet evaluated," not "evaluated and
  passed but didn't fit."
- Every prospect actually evaluated (pass or fail) gets a qualification_reason
  and qualified_at timestamp, so a human can see why a prospect landed where
  it did.
- A prospect's qualification_details/qualification_campaign_name are a frozen
  snapshot taken at evaluation time -- later edits to that campaign never
  change an already-evaluated prospect's stored breakdown.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Prospect, ProspectStatus, QualificationCampaign
from app.stages.qualification_engine import decide, evaluate_prospect


class QualifyResult:
    def __init__(self) -> None:
        self.qualified_ids: list[str] = []
        self.disqualified_count = 0
        self.queued_remaining = 0
        self.batch_size = 0


def _load_campaign(db: Session, campaign_id: int | None) -> QualificationCampaign:
    if campaign_id is not None:
        campaign = db.get(QualificationCampaign, campaign_id)
        if campaign is not None:
            return campaign
        # Falls through to the active-campaign lookup below if the given id
        # doesn't exist -- same defensive spirit as the "no active campaign"
        # fallback, rather than raising and stalling the whole batch.

    campaign = db.scalars(select(QualificationCampaign).where(QualificationCampaign.is_active.is_(True))).first()
    if campaign is None:
        # Defensive fallback only -- the 0004 migration always seeds one
        # active "Default" campaign. An empty campaign (no criteria) means
        # every prospect trivially qualifies (no mandatory/optional checks to
        # fail), which is at least a visible, inspectable state rather than
        # qualify_batch erroring out and stalling the auto pipeline.
        campaign = QualificationCampaign(name="Default", is_active=True, min_optional_matches=None)
        db.add(campaign)
        db.flush()
    return campaign


def qualify_batch(db: Session, *, batch_cap: int = 20, campaign_id: int | None = None) -> QualifyResult:
    result = QualifyResult()
    now = datetime.utcnow()

    campaign = _load_campaign(db, campaign_id)
    criteria = list(campaign.criteria)

    candidates = db.scalars(
        select(Prospect).where(Prospect.status == ProspectStatus.INGESTED).order_by(Prospect.ingested_at.asc())
    ).all()

    for prospect in candidates:
        if result.batch_size >= batch_cap:
            result.queued_remaining += 1
            continue

        company = db.get(Company, prospect.company_id)
        if company is None:
            # Data-integrity issue (should be unreachable -- Stage 1 always
            # creates a company), not a business-rule evaluation: leave
            # untouched rather than recording a misleading reason.
            continue

        criterion_results = evaluate_prospect(db, prospect, company, criteria)
        qualified, reason = decide(criterion_results, campaign.min_optional_matches)

        prospect.qualified_at = now
        prospect.qualification_details = [r.to_dict() for r in criterion_results]
        prospect.qualification_campaign_id = campaign.id
        prospect.qualification_campaign_name = campaign.name
        if qualified:
            prospect.status = ProspectStatus.QUALIFIED
            prospect.qualification_reason = reason
            result.qualified_ids.append(prospect.prospect_id)
            result.batch_size += 1
        else:
            prospect.status = ProspectStatus.DISQUALIFIED
            prospect.qualification_reason = reason
            result.disqualified_count += 1

    db.commit()
    return result
