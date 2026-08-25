"""Stage 8 - Risk flags.

Computed at READ time (called from GET /api/prospects/{id} and the review
queue endpoint) rather than persisted, so a flag can never go stale relative
to the underlying Finding/OutreachDraft rows after an edit -- there is no
RiskFlag table to keep in sync. Cheap enough to recompute on every read given
the small per-prospect finding count (well under a dozen rows).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.models import Company, Finding, FindingSlot, OutreachDraft, Prospect

STALE_SOURCE_DAYS = 90
LOW_CONFIDENCE_THRESHOLD = 0.6


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return url.lower()


def compute_risk_flags(
    prospect: Prospect,
    company: Company,
    findings: list[Finding],
    draft: OutreachDraft | None,
) -> list[dict]:
    flags: list[dict] = []
    now = datetime.utcnow()

    # STALE_SOURCE: best-effort -- we don't have the underlying page's
    # publish date, so we use retrieved_at as documented in the spec.
    stale = [f for f in findings if (now - f.retrieved_at) > timedelta(days=STALE_SOURCE_DAYS)]
    if stale:
        flags.append(
            {
                "flag": "STALE_SOURCE",
                "detail": f"{len(stale)} finding(s) retrieved more than {STALE_SOURCE_DAYS} days ago.",
            }
        )

    # SINGLE_SOURCE: every finding traces to the same domain.
    domains = {_domain(f.source_url) for f in findings}
    if findings and len(domains) == 1:
        flags.append(
            {
                "flag": "SINGLE_SOURCE",
                "detail": f"All {len(findings)} finding(s) trace to a single domain ({next(iter(domains))}).",
            }
        )

    # LOW_CONFIDENCE: any finding actually used in claims_used has confidence < threshold.
    if draft is not None and draft.claims_used:
        by_id = {f.finding_id: f for f in findings}
        low_conf_ids = [
            fid for fid in draft.claims_used if fid in by_id and by_id[fid].confidence < LOW_CONFIDENCE_THRESHOLD
        ]
        if low_conf_ids:
            flags.append(
                {
                    "flag": "LOW_CONFIDENCE",
                    "detail": f"{len(low_conf_ids)} claim(s) used in the draft rely on findings with confidence < {LOW_CONFIDENCE_THRESHOLD}.",
                }
            )

    # NAME_COLLISION: a PERSON_SIGNAL finding whose claim/source_url text
    # doesn't also mention the company name -- a signal the "person" found
    # may be a namesake at a different company.
    company_name_lower = (company.name or "").strip().lower()
    person_findings = [f for f in findings if f.slot == FindingSlot.PERSON_SIGNAL]
    if company_name_lower:
        collisions = [
            f for f in person_findings if company_name_lower not in f"{f.claim} {f.source_url}".lower()
        ]
        if collisions:
            flags.append(
                {
                    "flag": "NAME_COLLISION",
                    "detail": f"{len(collisions)} PERSON_SIGNAL finding(s) do not mention '{company.name}' -- possible namesake.",
                }
            )

    # NO_PERSON_SIGNAL: no PERSON_SIGNAL slot was filled at all.
    if not person_findings:
        flags.append({"flag": "NO_PERSON_SIGNAL", "detail": "No PERSON_SIGNAL finding was recorded for this prospect."})

    return flags
