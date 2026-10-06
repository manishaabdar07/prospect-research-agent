from __future__ import annotations

from sqlalchemy import select

from app.models import Company, Prospect, RoleBucket
from app.stages.stage1_ingest import (
    derive_role_bucket,
    derive_seniority,
    normalize_city,
    normalize_headcount,
)
from app.stages.stage1_ingest import ingest_csv


def test_normalize_headcount_range_midpoint():
    assert normalize_headcount("50-100") == 75


def test_normalize_headcount_single_value():
    assert normalize_headcount("120") == 120


def test_normalize_headcount_plus():
    assert normalize_headcount("500+") == 500


def test_normalize_headcount_unparseable_is_none():
    assert normalize_headcount("a lot of people") is None
    assert normalize_headcount(None) is None
    assert normalize_headcount("") is None


def test_normalize_city_canonicalizes_known_spellings():
    assert normalize_city("pune") == "Pune"
    assert normalize_city("  PIMPRI CHINCHWAD ") == "Pimpri-Chinchwad"
    assert normalize_city("hinjawadi") == "Hinjewadi"


def test_normalize_city_passes_through_unknown():
    assert normalize_city("Mumbai") == "Mumbai"


def test_derive_role_bucket_it_and_hr_and_other():
    assert derive_role_bucket("Chief Technology Officer") == RoleBucket.IT
    assert derive_role_bucket("Head of Human Resources") == RoleBucket.HR
    assert derive_role_bucket("Regional Sales Manager") == RoleBucket.OTHER


def test_derive_seniority():
    from app.models import Seniority

    assert derive_seniority("Chief Technology Officer") == Seniority.CXO
    assert derive_seniority("VP Engineering") == Seniority.VP
    assert derive_seniority("Director of Operations") == Seniority.DIRECTOR
    assert derive_seniority("Head of IT") == Seniority.HEAD
    assert derive_seniority("Software Engineer") == Seniority.OTHER


CSV_HAPPY_PATH = """Full Name,Company Name,Designation,City,Employees,LinkedIn URL,Email
Asha Kulkarni,Acme Forge Pvt Ltd,CTO,Pune,50-100,https://linkedin.com/in/asha,asha@acme.com
Ravi Sharma,Acme Forge Pvt Ltd,HR Head,pimpri chinchwad,80,,ravi@acme.com
"""


def test_ingest_csv_happy_path(db_session):
    result = ingest_csv(db_session, CSV_HAPPY_PATH.encode("utf-8"))
    assert result.ingested == 2
    assert result.rejected == []

    prospects = db_session.scalars(select(Prospect)).all()
    assert len(prospects) == 2

    companies = db_session.scalars(select(Company)).all()
    assert len(companies) == 1  # same company, deduped by stable slug
    assert companies[0].headcount == 75  # "50-100" -> midpoint
    assert companies[0].city == "Pune"

    asha = next(p for p in prospects if p.full_name == "Asha Kulkarni")
    assert asha.role_bucket == RoleBucket.IT


CSV_WITH_REJECTIONS = """Name,Company,Title,City
,Some Company,CTO,Pune
John Doe,,CTO,Pune  1 
Jane Roe,Widgets Inc,Head of HR,Pune
"""


def test_ingest_csv_rejects_missing_name_or_company(db_session):
    result = ingest_csv(db_session, CSV_WITH_REJECTIONS.encode("utf-8"))
    assert result.ingested == 1
    assert len(result.rejected) == 2

    reasons = {r["reason"] for r in result.rejected}
    assert "missing name" in reasons
    assert "missing company" in reasons

    # row numbers should point at the actual CSV rows (header is row 1)
    rows = {r["row"] for r in result.rejected}
    assert rows == {2, 3}


def test_ingest_csv_no_header_row_does_not_raise(db_session):
    result = ingest_csv(db_session, b"")
    assert result.ingested == 0
    assert len(result.rejected) == 1


def test_ingest_csv_tolerates_header_variants(db_session):
    csv_text = "name,company,title,city,headcount\nA B,Foo Co,IT Manager,Chakan,30\n"
    result = ingest_csv(db_session, csv_text.encode("utf-8"))
    assert result.ingested == 1
    assert result.rejected == []
