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
- Batch cap is a hard 20, enforced as a true short-circuit: once that many
  prospects have been evaluated and qualified, the rest of the INGESTED queue
  is left completely untouched (status stays INGESTED, qualification_reason
  stays None) for the next qualify run, rather than being evaluated now and
  discarded. "queued_remaining" therefore means "not yet evaluated," not
  "evaluated and passed but didn't fit."
- Every prospect actually evaluated (pass or fail) gets a qualification_reason
  and qualified_at timestamp, so a human can see why a prospect landed where
  it did -- previously a failing prospect just stayed at INGESTED forever with
  no recorded reason, which was indistinguishable from "not processed yet."
"""
from __future__ import annotations

import re
from datetime import datetime

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
        self.disqualified_count = 0
        self.queued_remaining = 0
        self.batch_size = 0


def _headcount_ok(headcount: int | None, hc_min: int, hc_max: int) -> bool:
    if headcount is None:
        return False  # fail-closed: unknown headcount does not qualify
    return hc_min <= headcount <= hc_max


def _city_ok(city: str) -> bool:
    return _normalize_city(city) in PUNE_METRO_ALLOWLIST


def _matched_exclusion(db: Session, prospect: Prospect, company: Company) -> ExclusionEntry | None:
    exclusions = db.scalars(select(ExclusionEntry)).all()
    for entry in exclusions:
        value_norm = entry.value.strip().lower()
        if entry.type == ExclusionType.COMPANY and company.name.strip().lower() == value_norm:
            return entry
        if entry.type == ExclusionType.PROSPECT and prospect.full_name.strip().lower() == value_norm:
            return entry
    return None


def _matched_duplicate(db: Session, prospect: Prospect) -> Prospect | None:
    """Dedupe against existing (already-evaluated) DB records.

    linkedin_url first, then (full_name, company_id) fallback. Only compares
    against prospects that have already left INGESTED (i.e. were evaluated in
    a prior qualify run), so two freshly-ingested rows for the same person in
    the *same* CSV batch don't get silently cross-dropped against each other.
    """
    query = select(Prospect).where(
        Prospect.prospect_id != prospect.prospect_id,
        Prospect.status != ProspectStatus.INGESTED,
    )
    existing = db.scalars(query).all()

    if prospect.linkedin_url:
        for other in existing:
            if other.linkedin_url and other.linkedin_url.strip().lower() == prospect.linkedin_url.strip().lower():
                return other
        return None  # has a linkedin_url and no match found -> not a dup via this path

    for other in existing:
        if (
            other.full_name.strip().lower() == prospect.full_name.strip().lower()
            and other.company_id == prospect.company_id
        ):
            return other
    return None


def _disqualify_reason(
    db: Session, prospect: Prospect, company: Company, headcount_min: int, headcount_max: int
) -> str | None:
    """Return a specific reason if `prospect` fails qualification, else None."""
    if not _headcount_ok(company.headcount, headcount_min, headcount_max):
        if company.headcount is None:
            return "Company headcount is unknown; cannot confirm it is within the supported range."
        return f"Headcount {company.headcount} is outside the supported range [{headcount_min}, {headcount_max}]."

    if not _city_ok(company.city):
        return f"City '{company.city}' is not in the supported Pune-metro area."

    exclusion = _matched_exclusion(db, prospect, company)
    if exclusion is not None:
        target = "company" if exclusion.type == ExclusionType.COMPANY else "prospect"
        reason_text = exclusion.reason or exclusion.value
        return f"Matches {target} exclusion list entry: {reason_text}."

    duplicate = _matched_duplicate(db, prospect)
    if duplicate is not None:
        matched_via = "LinkedIn URL" if prospect.linkedin_url else "name + company"
        return f"Duplicate of existing prospect {duplicate.prospect_id} ({duplicate.full_name}), matched by {matched_via}."

    return None


def qualify_batch(
    db: Session,
    *,
    batch_cap: int = 20,
    headcount_min: int = 10,
    headcount_max: int = 200,
) -> QualifyResult:
    result = QualifyResult()
    now = datetime.utcnow()

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

        reason = _disqualify_reason(db, prospect, company, headcount_min, headcount_max)
        prospect.qualified_at = now
        if reason is None:
            prospect.status = ProspectStatus.QUALIFIED
            prospect.qualification_reason = "Passed all qualification checks."
            result.qualified_ids.append(prospect.prospect_id)
            result.batch_size += 1
        else:
            prospect.status = ProspectStatus.DISQUALIFIED
            prospect.qualification_reason = reason
            result.disqualified_count += 1

    db.commit()
    return result
