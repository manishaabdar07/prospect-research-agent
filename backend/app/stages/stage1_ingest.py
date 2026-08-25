"""Stage 1 - Ingest (plain code, no LLM).

Parses an uploaded CSV into Company + Prospect rows. Tolerant of common
header-name variants. Never raises on a single bad row -- collects
{row, reason} rejections and keeps going. Rows missing name or company are
rejected; everything else is best-effort normalized.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.ids import company_id_from_name, new_prospect_id
from app.models import Company, Prospect, ProspectSource, ProspectStatus, RoleBucket, Seniority

# --------------------------------------------------------------------------
# Header mapping
# --------------------------------------------------------------------------

# Each canonical field maps to a list of accepted header spellings
# (compared case-insensitively, whitespace-stripped).
HEADER_ALIASES: dict[str, list[str]] = {
    "full_name": ["name", "full name", "fullname", "prospect name", "contact name"],
    "company_name": ["company", "company name", "organisation", "organization", "employer"],
    "title_raw": ["title", "designation", "job title", "role", "position"],
    "city": ["city", "location"],
    "headcount": ["headcount", "employees", "employee count", "company size", "size"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile", "li url"],
    "email": ["email", "email address", "e-mail"],
    "domain": ["domain", "website", "company domain", "company website"],
    "industry_raw": ["industry", "sector", "industry raw"],
}


def _normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def _build_header_index(fieldnames: list[str]) -> dict[str, str]:
    """Map canonical field name -> actual CSV column name present in the file."""
    normalized_to_actual = {_normalize_header(f): f for f in fieldnames}
    index: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized_to_actual:
                index[canonical] = normalized_to_actual[alias]
                break
    return index


# --------------------------------------------------------------------------
# Value normalization
# --------------------------------------------------------------------------

# Pune-metro area spellings: canonicalize casing/whitespace only, do not
# attempt fuzzy geocoding or aliasing beyond this.
CITY_CANON = {
    "pune": "Pune",
    "pimpri": "Pimpri-Chinchwad",
    "pimpri chinchwad": "Pimpri-Chinchwad",
    "pimpri-chinchwad": "Pimpri-Chinchwad",
    "chakan": "Chakan",
    "hinjewadi": "Hinjewadi",
    "hinjawadi": "Hinjewadi",
    "talegaon": "Talegaon",
    "talegaon dabhade": "Talegaon",
    "ranjangaon": "Ranjangaon",
    "chikhali": "Chikhali",
}


def normalize_city(raw: str | None) -> str:
    if not raw:
        return ""
    key = re.sub(r"\s+", " ", raw.strip().lower())
    return CITY_CANON.get(key, raw.strip())


_HEADCOUNT_RANGE_RE = re.compile(r"(\d[\d,]*)\s*[-–to]+\s*(\d[\d,]*)", re.IGNORECASE)
_HEADCOUNT_SINGLE_RE = re.compile(r"(\d[\d,]*)")
_HEADCOUNT_PLUS_RE = re.compile(r"(\d[\d,]*)\s*\+")


def normalize_headcount(raw: str | None) -> int | None:
    """Parse a headcount value/range into a midpoint int. Returns None if unparseable."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    range_match = _HEADCOUNT_RANGE_RE.search(raw)
    if range_match:
        lo = int(range_match.group(1).replace(",", ""))
        hi = int(range_match.group(2).replace(",", ""))
        return (lo + hi) // 2
    plus_match = _HEADCOUNT_PLUS_RE.search(raw)
    if plus_match:
        return int(plus_match.group(1).replace(",", ""))
    single_match = _HEADCOUNT_SINGLE_RE.search(raw)
    if single_match:
        return int(single_match.group(1).replace(",", ""))
    return None


# Role bucket regexes -- deliberately simple, no LLM. Order matters: IT
# checked before HR to avoid e.g. "HR Systems" false-matching OTHER.
IT_PATTERNS = [
    r"\bit\b",
    r"information technology",
    r"\bcto\b",
    r"chief technology",
    r"\btechnology\b",
    r"\bsystems?\b",
    r"\berp\b",
    r"infrastructure",
    r"\bnetwork\b",
    r"software",
    r"\bciso\b",
    r"information security",
    r"\bdevops\b",
]
HR_PATTERNS = [
    r"\bhr\b",
    r"human resources?",
    r"\bpeople\b",
    r"\btalent\b",
    r"recruit(ing|ment)?",
    r"\bchro\b",
    r"chief human resources",
    r"personnel",
]

_IT_RE = re.compile("|".join(IT_PATTERNS), re.IGNORECASE)
_HR_RE = re.compile("|".join(HR_PATTERNS), re.IGNORECASE)

SENIORITY_PATTERNS: list[tuple[re.Pattern, Seniority]] = [
    (re.compile(r"\b(ceo|cto|cfo|coo|chro|ciso|chief\s+\w+\s+officer)\b", re.IGNORECASE), Seniority.CXO),
    (re.compile(r"\b(vp|vice president)\b", re.IGNORECASE), Seniority.VP),
    (re.compile(r"\bdirector\b", re.IGNORECASE), Seniority.DIRECTOR),
    (re.compile(r"\bhead\b", re.IGNORECASE), Seniority.HEAD),
]


def derive_role_bucket(title_raw: str) -> RoleBucket:
    if not title_raw:
        return RoleBucket.OTHER
    if _IT_RE.search(title_raw):
        return RoleBucket.IT
    if _HR_RE.search(title_raw):
        return RoleBucket.HR
    return RoleBucket.OTHER


def derive_seniority(title_raw: str) -> Seniority:
    if not title_raw:
        return Seniority.OTHER
    for pattern, level in SENIORITY_PATTERNS:
        if pattern.search(title_raw):
            return level
    return Seniority.OTHER


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------


class IngestResult:
    def __init__(self) -> None:
        self.ingested = 0
        self.rejected: list[dict] = []


def ingest_csv(db: Session, file_bytes: bytes) -> IngestResult:
    result = IngestResult()

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.rejected.append({"row": 0, "reason": "CSV has no header row"})
        return result

    header_index = _build_header_index(list(reader.fieldnames))

    # Companies created earlier in THIS batch are still merely "pending" in
    # the session (not flushed), so db.get() alone won't see them and two
    # rows for the same company in one CSV would otherwise try to INSERT the
    # same company_id twice. Track them locally for the duration of the batch.
    companies_in_batch: dict[str, Company] = {}

    for row_num, row in enumerate(reader, start=2):  # row 1 is the header
        try:
            full_name = _get(row, header_index, "full_name")
            company_name = _get(row, header_index, "company_name")

            if not full_name:
                result.rejected.append({"row": row_num, "reason": "missing name"})
                continue
            if not company_name:
                result.rejected.append({"row": row_num, "reason": "missing company"})
                continue

            title_raw = _get(row, header_index, "title_raw") or ""
            city_raw = _get(row, header_index, "city") or ""
            headcount_raw = _get(row, header_index, "headcount")
            linkedin_url = _get(row, header_index, "linkedin_url") or None
            email = _get(row, header_index, "email") or None
            domain = _get(row, header_index, "domain") or None
            industry_raw = _get(row, header_index, "industry_raw") or ""

            city = normalize_city(city_raw)
            headcount = normalize_headcount(headcount_raw)

            company_id = company_id_from_name(company_name)
            company = companies_in_batch.get(company_id) or db.get(Company, company_id)
            if company is None:
                company = Company(
                    company_id=company_id,
                    name=company_name.strip(),
                    domain=domain.strip() if domain else None,
                    headcount=headcount,
                    city=city,
                    industry_raw=industry_raw.strip(),
                )
                db.add(company)
                companies_in_batch[company_id] = company
            else:
                # Fill in gaps from this row without clobbering existing data.
                if headcount is not None and company.headcount is None:
                    company.headcount = headcount
                if domain and not company.domain:
                    company.domain = domain.strip()
                if not company.city and city:
                    company.city = city

            prospect = Prospect(
                prospect_id=new_prospect_id(),
                company_id=company_id,
                full_name=full_name.strip(),
                title_raw=title_raw.strip(),
                role_bucket=derive_role_bucket(title_raw),
                seniority=derive_seniority(title_raw),
                linkedin_url=linkedin_url.strip() if linkedin_url else None,
                email=email.strip() if email else None,
                source=ProspectSource.csv,
                ingested_at=datetime.utcnow(),
                status=ProspectStatus.INGESTED,
            )
            db.add(prospect)
            result.ingested += 1
        except Exception as exc:  # never raise on a bad row
            result.rejected.append({"row": row_num, "reason": f"unexpected error: {exc}"})

    db.commit()
    return result


def _get(row: dict, header_index: dict[str, str], canonical: str) -> str | None:
    actual = header_index.get(canonical)
    if actual is None:
        return None
    value = row.get(actual)
    if value is None:
        return None
    value = value.strip()
    return value or None
