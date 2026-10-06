from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import QualifyRequest, QualifyResponse
from app.stages.stage2_qualify import qualify_batch

router = APIRouter(tags=["qualify"])


@router.post("/qualify", response_model=QualifyResponse)
def qualify(body: QualifyRequest = QualifyRequest(), db: Session = Depends(get_db)) -> QualifyResponse:
    settings = get_settings()
    result = qualify_batch(db, batch_cap=settings.QUALIFY_BATCH_CAP, campaign_id=body.campaign_id)
    return QualifyResponse(
        qualified=result.qualified_ids,
        disqualified_count=result.disqualified_count,
        queued_remaining=result.queued_remaining,
        batch_size=result.batch_size,
    )
