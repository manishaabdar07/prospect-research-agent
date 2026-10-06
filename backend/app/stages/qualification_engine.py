"""Generic, DB-configuration-driven Stage 2 qualification engine.

Replaces the old hardcoded `_disqualify_reason()` (headcount/city values
baked into Python) with a small rule engine that reads its criteria from the
`qualification_criteria` table. Five criterion types (RANGE, LIST,
EXACT_MATCH, CONTAINS, BOOLEAN) compare a Prospect/Company field against
admin-configured values; two more (EXCLUSION_LIST, DUPLICATE_CHECK) are
structural DB lookups that were never "a value to configure" in the first
place, so they stay wired to their own dedicated functions below instead of
being forced into a field/value shape.

Security note: `field` on a QualificationCriteria row is a dotted name that
must exist in FIELD_ACCESSORS. This is an allowlist, not arbitrary getattr --
DB-driven configuration must never become a code-execution surface.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CriterionStatus,
    CriterionType,
    ExclusionEntry,
    ExclusionType,
    Prospect,
    ProspectStatus,
    QualificationCriteria,
)

# --------------------------------------------------------------------------
# Field allowlist -- the only fields a DB-configured criterion may read.
# --------------------------------------------------------------------------

FIELD_ACCESSORS: dict[str, Callable[[Prospect, Company], Any]] = {
    "company.headcount": lambda p, c: c.headcount,
    "company.city": lambda p, c: c.city,
    "company.industry_raw": lambda p, c: c.industry_raw,
    "company.domain": lambda p, c: c.domain,
    "prospect.role_bucket": lambda p, c: p.role_bucket.value if p.role_bucket is not None else None,
    "prospect.seniority": lambda p, c: p.seniority.value if p.seniority is not None else None,
    "prospect.title_raw": lambda p, c: p.title_raw,
}


@dataclass
class CriterionResult:
    criterion_name: str
    criterion_type: str
    expected: Any
    actual: Any
    status: str  # CriterionStatus value
    reason: str
    mandatory: bool = True  # set from the owning criterion in evaluate_prospect()

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize(value: Any) -> str:
    return str(value).strip().lower()


# --------------------------------------------------------------------------
# Generic field-based evaluators
# --------------------------------------------------------------------------


def _evaluate_range(name: str, actual: Any, config: dict) -> CriterionResult:
    lo, hi = config.get("min"), config.get("max")
    expected = {"min": lo, "max": hi}
    if actual is None:
        return CriterionResult(name, CriterionType.RANGE.value, expected, None, CriterionStatus.UNKNOWN.value,
                                f"{name}: value is unknown; cannot confirm it is within [{lo}, {hi}].")
    try:
        actual_num = float(actual)
    except (TypeError, ValueError):
        return CriterionResult(name, CriterionType.RANGE.value, expected, actual, CriterionStatus.UNKNOWN.value,
                                f"{name}: value {actual!r} is not numeric.")
    if (lo is None or actual_num >= lo) and (hi is None or actual_num <= hi):
        return CriterionResult(name, CriterionType.RANGE.value, expected, actual, CriterionStatus.MATCHED.value,
                                f"{name}: {actual} is within [{lo}, {hi}].")
    return CriterionResult(name, CriterionType.RANGE.value, expected, actual, CriterionStatus.NOT_MATCHED.value,
                            f"{name}: {actual} is outside the configured range [{lo}, {hi}].")


def _evaluate_list(name: str, actual: Any, config: dict) -> CriterionResult:
    allowed = config.get("allowed_values") or []
    expected = allowed
    if actual is None or _normalize(actual) == "":
        return CriterionResult(name, CriterionType.LIST.value, expected, actual, CriterionStatus.UNKNOWN.value,
                                f"{name}: value is unknown.")
    allowed_norm = {_normalize(v) for v in allowed}
    if _normalize(actual) in allowed_norm:
        return CriterionResult(name, CriterionType.LIST.value, expected, actual, CriterionStatus.MATCHED.value,
                                f"{name}: {actual!r} is in the configured allowed values.")
    return CriterionResult(name, CriterionType.LIST.value, expected, actual, CriterionStatus.NOT_MATCHED.value,
                            f"{name}: {actual!r} is not in the configured allowed values {allowed}.")


def _evaluate_exact_match(name: str, actual: Any, config: dict) -> CriterionResult:
    expected = config.get("value")
    if actual is None:
        return CriterionResult(name, CriterionType.EXACT_MATCH.value, expected, actual, CriterionStatus.UNKNOWN.value,
                                f"{name}: value is unknown.")
    if _normalize(actual) == _normalize(expected):
        return CriterionResult(name, CriterionType.EXACT_MATCH.value, expected, actual, CriterionStatus.MATCHED.value,
                                f"{name}: {actual!r} matches the configured value.")
    return CriterionResult(name, CriterionType.EXACT_MATCH.value, expected, actual, CriterionStatus.NOT_MATCHED.value,
                            f"{name}: {actual!r} does not match the configured value {expected!r}.")


def _evaluate_contains(name: str, actual: Any, config: dict) -> CriterionResult:
    tokens = config.get("any_of") or []
    expected = tokens
    if actual is None or _normalize(actual) == "":
        return CriterionResult(name, CriterionType.CONTAINS.value, expected, actual, CriterionStatus.UNKNOWN.value,
                                f"{name}: value is unknown.")
    actual_norm = _normalize(actual)
    if any(_normalize(t) in actual_norm for t in tokens):
        return CriterionResult(name, CriterionType.CONTAINS.value, expected, actual, CriterionStatus.MATCHED.value,
                                f"{name}: {actual!r} contains one of the configured values.")
    return CriterionResult(name, CriterionType.CONTAINS.value, expected, actual, CriterionStatus.NOT_MATCHED.value,
                            f"{name}: {actual!r} contains none of the configured values {tokens}.")


def _evaluate_boolean(name: str, actual: Any, config: dict) -> CriterionResult:
    expected = config.get("expected", True)
    if actual is None:
        return CriterionResult(name, CriterionType.BOOLEAN.value, expected, actual, CriterionStatus.UNKNOWN.value,
                                f"{name}: value is unknown.")
    if bool(actual) == bool(expected):
        return CriterionResult(name, CriterionType.BOOLEAN.value, expected, actual, CriterionStatus.MATCHED.value,
                                f"{name}: {bool(actual)} matches the configured expectation.")
    return CriterionResult(name, CriterionType.BOOLEAN.value, expected, actual, CriterionStatus.NOT_MATCHED.value,
                            f"{name}: {bool(actual)} does not match the configured expectation {bool(expected)}.")


_FIELD_EVALUATORS: dict[CriterionType, Callable[[str, Any, dict], CriterionResult]] = {
    CriterionType.RANGE: _evaluate_range,
    CriterionType.LIST: _evaluate_list,
    CriterionType.EXACT_MATCH: _evaluate_exact_match,
    CriterionType.CONTAINS: _evaluate_contains,
    CriterionType.BOOLEAN: _evaluate_boolean,
}


# --------------------------------------------------------------------------
# Special gates -- structural DB lookups, not field/value comparisons.
# Unchanged logic from the old stage2_qualify.py, just relocated here.
# --------------------------------------------------------------------------


def matched_exclusion(db: Session, prospect: Prospect, company: Company) -> ExclusionEntry | None:
    exclusions = db.scalars(select(ExclusionEntry)).all()
    for entry in exclusions:
        value_norm = entry.value.strip().lower()
        if entry.type == ExclusionType.COMPANY and company.name.strip().lower() == value_norm:
            return entry
        if entry.type == ExclusionType.PROSPECT and prospect.full_name.strip().lower() == value_norm:
            return entry
    return None


def matched_duplicate(db: Session, prospect: Prospect) -> Prospect | None:
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


def _evaluate_exclusion_list(db: Session, prospect: Prospect, company: Company, name: str) -> CriterionResult:
    entry = matched_exclusion(db, prospect, company)
    if entry is None:
        return CriterionResult(name, CriterionType.EXCLUSION_LIST.value, "not on exclusion list", None,
                                CriterionStatus.MATCHED.value, f"{name}: no exclusion list match.")
    target = "company" if entry.type == ExclusionType.COMPANY else "prospect"
    reason_text = entry.reason or entry.value
    return CriterionResult(name, CriterionType.EXCLUSION_LIST.value, "not on exclusion list", entry.value,
                            CriterionStatus.NOT_MATCHED.value,
                            f"Matches {target} exclusion list entry: {reason_text}.")


def _evaluate_duplicate_check(db: Session, prospect: Prospect, name: str) -> CriterionResult:
    duplicate = matched_duplicate(db, prospect)
    if duplicate is None:
        return CriterionResult(name, CriterionType.DUPLICATE_CHECK.value, "no duplicate", None,
                                CriterionStatus.MATCHED.value, f"{name}: no duplicate found.")
    matched_via = "LinkedIn URL" if prospect.linkedin_url else "name + company"
    return CriterionResult(
        name, CriterionType.DUPLICATE_CHECK.value, "no duplicate", duplicate.prospect_id,
        CriterionStatus.NOT_MATCHED.value,
        f"Duplicate of existing prospect {duplicate.prospect_id} ({duplicate.full_name}), matched by {matched_via}.",
    )


# --------------------------------------------------------------------------
# Public engine API
# --------------------------------------------------------------------------


def evaluate_prospect(
    db: Session, prospect: Prospect, company: Company, criteria: list[QualificationCriteria]
) -> list[CriterionResult]:
    """Evaluate every enabled criterion (in priority order) for one prospect."""
    results: list[CriterionResult] = []
    for criterion in sorted((c for c in criteria if c.enabled), key=lambda c: c.priority):
        ctype = criterion.criterion_type
        if ctype == CriterionType.EXCLUSION_LIST:
            result = _evaluate_exclusion_list(db, prospect, company, criterion.name)
        elif ctype == CriterionType.DUPLICATE_CHECK:
            result = _evaluate_duplicate_check(db, prospect, criterion.name)
        else:
            evaluator = _FIELD_EVALUATORS[ctype]
            accessor = FIELD_ACCESSORS.get(criterion.field or "")
            actual = accessor(prospect, company) if accessor is not None else None
            result = evaluator(criterion.name, actual, criterion.configuration or {})
        result.mandatory = criterion.mandatory
        results.append(result)
    return results


def decide(results: list[CriterionResult], min_optional_matches: int | None) -> tuple[bool, str]:
    """Apply the campaign's decision rule to a prospect's criterion results.

    Every mandatory criterion must MATCH -- a single failure there disqualifies
    outright, regardless of how many optional criteria matched (this is what
    the old hardcoded "Exclusion List/Duplicate Check always gate" behavior
    generalizes into: those two are simply seeded as mandatory=True). Among
    the optional criteria, at least `min_optional_matches` must MATCH (None
    means all optional criteria must match too). UNKNOWN counts as
    not-matched either way, never silently a pass.

    `min_optional_matches` is clamped to the number of optional criteria that
    actually exist -- a campaign with every criterion marked mandatory (zero
    optional ones) but a leftover/misconfigured min_optional_matches > 0
    would otherwise demand more optional matches than could ever exist,
    silently disqualifying every prospect no matter how well they match.
    """
    mandatory = [r for r in results if r.mandatory]
    optional = [r for r in results if not r.mandatory]

    failed_mandatory = [r for r in mandatory if r.status != CriterionStatus.MATCHED.value]
    if failed_mandatory:
        return False, failed_mandatory[0].reason

    matched_optional = [r for r in optional if r.status == CriterionStatus.MATCHED.value]
    required = min(min_optional_matches, len(optional)) if min_optional_matches is not None else len(optional)
    if len(matched_optional) >= required:
        return True, "Passed all qualification checks."

    failed_optional = [r for r in optional if r.status != CriterionStatus.MATCHED.value]
    return False, (
        failed_optional[0].reason if failed_optional else "Did not meet the minimum number of matching optional criteria."
    )
