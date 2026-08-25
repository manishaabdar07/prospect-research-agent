from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, Prospect, ProspectStatus, ResearchFindings
from app.schemas import DisqualifiedItem

router = APIRouter(tags=["disqualified"])


@router.get("/disqualified", response_model=list[DisqualifiedItem])
def list_disqualified(db: Session = Depends(get_db)) -> list[DisqualifiedItem]:
    prospects = db.scalars(
        select(Prospect).where(Prospect.status == ProspectStatus.DISQUALIFIED).order_by(Prospect.ingested_at.desc())
    ).all()

    items: list[DisqualifiedItem] = []
    for p in prospects:
        company = db.get(Company, p.company_id)
        research = db.get(ResearchFindings, p.prospect_id)
        items.append(
            DisqualifiedItem(
                prospect_id=p.prospect_id,
                full_name=p.full_name,
                company_name=company.name if company else "",
                hook_strength=research.hook_strength if research else None,
                terminal_reason=research.terminal_reason if research else None,
                agent_notes=research.agent_notes if research else None,
            )
        )
    return items
