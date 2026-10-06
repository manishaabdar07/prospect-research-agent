"""Admin API for Stage 2's DB-configured qualification campaigns and their
criteria. See app/stages/qualification_engine.py for how these are consumed,
and app/stages/stage2_qualify.py for how a campaign is selected for a run."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import QualificationCampaign, QualificationCriteria
from app.schemas import (
    QualificationCampaignCreate,
    QualificationCampaignSchema,
    QualificationCampaignUpdate,
    QualificationCriterionCreate,
    QualificationCriterionSchema,
    QualificationCriterionUpdate,
)

router = APIRouter(tags=["qualification-criteria"])


def _get_campaign_or_404(db: Session, campaign_id: int) -> QualificationCampaign:
    campaign = db.get(QualificationCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="qualification campaign not found")
    return campaign


def _get_criterion_or_404(db: Session, criterion_id: int) -> QualificationCriteria:
    criterion = db.get(QualificationCriteria, criterion_id)
    if criterion is None:
        raise HTTPException(status_code=404, detail="qualification criterion not found")
    return criterion


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------


@router.get("/qualification-campaigns", response_model=list[QualificationCampaignSchema])
def list_campaigns(db: Session = Depends(get_db)) -> list[QualificationCampaign]:
    return list(db.scalars(select(QualificationCampaign).order_by(QualificationCampaign.id.asc())).all())


@router.post("/qualification-campaigns", response_model=QualificationCampaignSchema, status_code=201)
def create_campaign(body: QualificationCampaignCreate, db: Session = Depends(get_db)) -> QualificationCampaign:
    campaign = QualificationCampaign(**body.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.put("/qualification-campaigns/{campaign_id}", response_model=QualificationCampaignSchema)
def update_campaign(
    campaign_id: int, body: QualificationCampaignUpdate, db: Session = Depends(get_db)
) -> QualificationCampaign:
    campaign = _get_campaign_or_404(db, campaign_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(campaign, key, value)
    campaign.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/qualification-campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)) -> None:
    campaign = _get_campaign_or_404(db, campaign_id)
    if campaign.is_active:
        raise HTTPException(
            status_code=400,
            detail="cannot delete the active campaign -- activate another campaign first",
        )
    db.delete(campaign)
    db.commit()


@router.post("/qualification-campaigns/{campaign_id}/activate", response_model=QualificationCampaignSchema)
def activate_campaign(campaign_id: int, db: Session = Depends(get_db)) -> QualificationCampaign:
    campaign = _get_campaign_or_404(db, campaign_id)
    for other in db.scalars(select(QualificationCampaign).where(QualificationCampaign.id != campaign_id)).all():
        if other.is_active:
            other.is_active = False
            other.updated_at = datetime.utcnow()
    campaign.is_active = True
    campaign.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(campaign)
    return campaign


# --------------------------------------------------------------------------
# Criteria (scoped to a campaign for listing/creation; id is globally unique
# for update/delete, matching the flat convention used elsewhere in this API)
# --------------------------------------------------------------------------


@router.get("/qualification-campaigns/{campaign_id}/criteria", response_model=list[QualificationCriterionSchema])
def list_campaign_criteria(campaign_id: int, db: Session = Depends(get_db)) -> list[QualificationCriteria]:
    _get_campaign_or_404(db, campaign_id)
    return list(
        db.scalars(
            select(QualificationCriteria)
            .where(QualificationCriteria.campaign_id == campaign_id)
            .order_by(QualificationCriteria.priority.asc())
        ).all()
    )


@router.post(
    "/qualification-campaigns/{campaign_id}/criteria",
    response_model=QualificationCriterionSchema,
    status_code=201,
)
def create_campaign_criterion(
    campaign_id: int, body: QualificationCriterionCreate, db: Session = Depends(get_db)
) -> QualificationCriteria:
    _get_campaign_or_404(db, campaign_id)
    criterion = QualificationCriteria(campaign_id=campaign_id, **body.model_dump())
    db.add(criterion)
    db.commit()
    db.refresh(criterion)
    return criterion


@router.put("/qualification-criteria/{criterion_id}", response_model=QualificationCriterionSchema)
def update_criterion(
    criterion_id: int, body: QualificationCriterionUpdate, db: Session = Depends(get_db)
) -> QualificationCriteria:
    criterion = _get_criterion_or_404(db, criterion_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(criterion, key, value)
    criterion.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(criterion)
    return criterion


@router.delete("/qualification-criteria/{criterion_id}", status_code=204)
def delete_criterion(criterion_id: int, db: Session = Depends(get_db)) -> None:
    criterion = _get_criterion_or_404(db, criterion_id)
    db.delete(criterion)
    db.commit()
