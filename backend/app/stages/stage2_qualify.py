"""Stage 2 - Qualify (plain code, no LLM).

Judgment calls (see README for the full list):
- Unknown/null headcount is FAIL-CLOSED: a company with no headcount data
  does NOT auto-pass qualification. Rationale: the spec's qualification
  criterion is a headcount band (10-200), and silently passing unknowns
  would let arbitrarily large or tiny companies into the batch, defeating
  the point of the filter. This can be revisited once a headcount-enrichment
  step exists.
- Dedupe order: linkedin_url first (strong identity signal when present),
  then (full_name, company_id) as a fallback for prospects without a
  LinkedIn URL.
- Batch cap is a hard 20. Anything qualifying beyond the cap is left at
  status INGESTED (not QUALIFIED) so it is picked up by the next qualify run
  instead of being lost.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, ExclusionEntry, ExclusionType, Prospect, ProspectStatus

# Pune-metro allowlist. Compared case-insensitively against the normalized
# city value set by Stage 1. Extend this set as the target geography grows.
PUNE_METRO_ALLOWLIST = {
    "pune",
    "pimpri-chinchwad",
    "chakan",
    "hinjewadi",
    "talegaon",
    "ranjangaon",
    "chikhali",
    "wagholi",
    "hadapsar",
    "baner",
    "kharadi",
    "bhosari",
    "manjari",
    "shirwal",
}


def _normalize_city(city: str) -> str:
    return re.sub(r"\s+", " ", (city or "").strip().lower())


class QualifyResult:
    def __init__(self) -> None:
        self.qualified_ids: list[str] = []
        self.queued_remaining = 0
        self.batch_size = 0


def _headcount_ok(headcount: int | None, hc_min: int, hc_max: int) -> bool:
    if headcount is None:
        return False  # fail-closed: unknown headcount does not qualify
    return hc_min <= headcount <= hc_max


def _city_ok(city: str) -> bool:
    return _normalize_city(city) in PUNE_METRO_ALLOWLIST


def _is_excluded(db: Session, prospect: Prospect, company: Company) -> bool:
    exclusions = db.scalars(select(ExclusionEntry)).all()
    for entry in exclusions:
        value_norm = entry.value.strip().lower()
        if entry.type == ExclusionType.COMPANY and company.name.strip().lower() == value_norm:
            return True
        if entry.type == ExclusionType.PROSPECT and prospect.full_name.strip().lower() == value_norm:
            return True
    return False


def _is_duplicate(db: Session, prospect: Prospect) -> bool:
    """Dedupe against existing (already-processed) DB records.

    linkedin_url first, then (full_name, company_id) fallback. Only compares
    against prospects that have already progressed past INGESTED (i.e. were
    qualified in a prior run), so two freshly-ingested rows for the same
    person in the *same* CSV batch don't get silently cross-dropped against
    each other -- Stage 1 already creates a row per CSV line; Stage 2 only
    dedupes against prospects qualified in a previous run.
    """
    query = select(Prospect).where(
        Prospect.prospect_id != prospect.prospect_id,
        Prospect.status != ProspectStatus.INGESTED,
    )
    existing = db.scalars(query).all()

    if prospect.linkedin_url:
        for other in existing:
            if other.linkedin_url and other.linkedin_url.strip().lower() == prospect.linkedin_url.strip().lower():
                return True
        return False  # has a linkedin_url and no match found -> not a dup via this path

    for other in existing:
        if (
            other.full_name.strip().lower() == prospect.full_name.strip().lower()
            and other.company_id == prospect.company_id
        ):
            return True
    return False


def qualify_batch(
    db: Session,
    *,
    batch_cap: int = 20,
    headcount_min: int = 10,
    headcount_max: int = 200,
) -> QualifyResult:
    result = QualifyResult()

    candidates = db.scalars(
        select(Prospect).where(Prospect.status == ProspectStatus.INGESTED).order_by(Prospect.ingested_at.asc())
    ).all()

    passing: list[Prospect] = []
    for prospect in candidates:
        company = db.get(Company, prospect.company_id)
        if company is None:
            continue
        if not _headcount_ok(company.headcount, headcount_min, headcount_max):
            continue
        if not _city_ok(company.city):
            continue
        if _is_excluded(db, prospect, company):
            continue
        if _is_duplicate(db, prospect):
            continue
        passing.append(prospect)

    batch = passing[:batch_cap]
    remainder = passing[batch_cap:]

    for prospect in batch:
        prospect.status = ProspectStatus.QUALIFIED
        result.qualified_ids.append(prospect.prospect_id)

    # remainder (and everything that failed a filter) stays at INGESTED.
    result.queued_remaining = len(remainder)
    result.batch_size = len(batch)

    db.commit()
    return result
