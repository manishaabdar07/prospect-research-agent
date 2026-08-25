from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import QualifyRequest, QualifyResponse
from app.stages.stage2_qualify import qualify_batch

router = APIRouter(tags=["qualify"])


@router.post("/qualify", response_model=QualifyResponse)
def qualify(_body: QualifyRequest = QualifyRequest(), db: Session = Depends(get_db)) -> QualifyResponse:
    settings = get_settings()
    result = qualify_batch(
        db,
        batch_cap=settings.QUALIFY_BATCH_CAP,
        headcount_min=settings.QUALIFY_HEADCOUNT_MIN,
        headcount_max=settings.QUALIFY_HEADCOUNT_MAX,
    )
    return QualifyResponse(
        qualified=result.qualified_ids,
        queued_remaining=result.queued_remaining,
        batch_size=result.batch_size,
    )
