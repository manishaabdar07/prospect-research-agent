from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.models import (
    Company,
    ExclusionEntry,
    ExclusionType,
    Prospect,
    ProspectSource,
    ProspectStatus,
    RoleBucket,
    Seniority,
)
from app.stages.stage2_qualify import qualify_batch

BATCH_CAP = 20
HC_MIN = 10
HC_MAX = 200


def _make_company(db, company_id: str, *, headcount, city: str, name: str | None = None) -> Company:
    c = Company(company_id=company_id, name=name or company_id, domain=None, headcount=headcount, city=city, industry_raw="")
    db.add(c)
    return c


def _make_prospect(
    db,
    prospect_id: str,
    company_id: str,
    *,
    full_name: str = "Test Person",
    linkedin_url: str | None = None,
    status: ProspectStatus = ProspectStatus.INGESTED,
) -> Prospect:
    p = Prospect(
        prospect_id=prospect_id,
        company_id=company_id,
        full_name=full_name,
        title_raw="IT Manager",
        role_bucket=RoleBucket.IT,
        seniority=Seniority.OTHER,
        linkedin_url=linkedin_url,
        email=None,
        source=ProspectSource.csv,
        ingested_at=datetime.utcnow(),
        status=status,
    )
    db.add(p)
    return p


def _run(db):
    return qualify_batch(db, batch_cap=BATCH_CAP, headcount_min=HC_MIN, headcount_max=HC_MAX)


def test_qualify_passes_valid_candidate(db_session):
    _make_company(db_session, "co-1", headcount=50, city="Pune")
    p = _make_prospect(db_session, "pr-1", "co-1")
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == ["pr-1"]
    assert result.batch_size == 1
    assert result.disqualified_count == 0
    assert result.queued_remaining == 0
    db_session.refresh(p)
    assert p.status == ProspectStatus.QUALIFIED
    assert p.qualification_reason == "Passed all qualification checks."
    assert p.qualified_at is not None


def test_qualify_unknown_headcount_fails_closed(db_session):
    _make_company(db_session, "co-1", headcount=None, city="Pune")
    p = _make_prospect(db_session, "pr-1", "co-1")
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []
    assert result.disqualified_count == 1
    db_session.refresh(p)
    # Evaluated and rejected -- not left at INGESTED, and the reason is
    # recorded so a human can see why.
    assert p.status == ProspectStatus.DISQUALIFIED
    assert p.qualification_reason is not None
    assert "headcount" in p.qualification_reason.lower()
    assert p.qualified_at is not None


def test_qualify_headcount_out_of_band_fails(db_session):
    _make_company(db_session, "co-1", headcount=5, city="Pune")
    p1 = _make_prospect(db_session, "pr-1", "co-1")
    _make_company(db_session, "co-2", headcount=500, city="Pune")
    p2 = _make_prospect(db_session, "pr-2", "co-2")
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []
    assert result.disqualified_count == 2
    db_session.refresh(p1)
    db_session.refresh(p2)
    assert p1.status == ProspectStatus.DISQUALIFIED
    assert "5" in p1.qualification_reason
    assert p2.status == ProspectStatus.DISQUALIFIED
    assert "500" in p2.qualification_reason


def test_qualify_city_not_in_allowlist_fails(db_session):
    _make_company(db_session, "co-1", headcount=50, city="Mumbai")
    p = _make_prospect(db_session, "pr-1", "co-1")
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []
    db_session.refresh(p)
    assert p.status == ProspectStatus.DISQUALIFIED
    assert "Mumbai" in p.qualification_reason


def test_qualify_excludes_company_on_exclusion_list(db_session):
    _make_company(db_session, "co-1", headcount=50, city="Pune", name="Blocked Co")
    p = _make_prospect(db_session, "pr-1", "co-1")
    db_session.add(ExclusionEntry(type=ExclusionType.COMPANY, value="Blocked Co", reason="existing client"))
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []
    db_session.refresh(p)
    assert p.status == ProspectStatus.DISQUALIFIED
    assert "existing client" in p.qualification_reason


def test_qualify_excludes_prospect_on_exclusion_list(db_session):
    _make_company(db_session, "co-1", headcount=50, city="Pune")
    p = _make_prospect(db_session, "pr-1", "co-1", full_name="Do Not Contact")
    db_session.add(ExclusionEntry(type=ExclusionType.PROSPECT, value="Do Not Contact", reason="past client"))
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []
    db_session.refresh(p)
    assert p.status == ProspectStatus.DISQUALIFIED
    assert "past client" in p.qualification_reason


def test_qualify_dedupes_by_linkedin_url_against_prior_run(db_session):
    _make_company(db_session, "co-1", headcount=50, city="Pune")
    # Already qualified in a prior run.
    _make_prospect(db_session, "pr-old", "co-1", linkedin_url="https://linkedin.com/in/same", status=ProspectStatus.QUALIFIED)
    # New row, same linkedin_url, still INGESTED.
    p_new = _make_prospect(db_session, "pr-new", "co-1", linkedin_url="https://linkedin.com/in/same")
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []  # deduped against pr-old
    db_session.refresh(p_new)
    assert p_new.status == ProspectStatus.DISQUALIFIED
    assert "pr-old" in p_new.qualification_reason


def test_qualify_dedupes_by_name_and_company_fallback(db_session):
    _make_company(db_session, "co-1", headcount=50, city="Pune")
    _make_prospect(db_session, "pr-old", "co-1", full_name="Same Person", status=ProspectStatus.RESEARCH_COMPLETED)
    p_new = _make_prospect(db_session, "pr-new", "co-1", full_name="Same Person")
    db_session.commit()

    result = _run(db_session)

    assert result.qualified_ids == []
    db_session.refresh(p_new)
    assert p_new.status == ProspectStatus.DISQUALIFIED
    assert "pr-old" in p_new.qualification_reason


def test_qualify_caps_batch_at_20_and_keeps_remainder_queued(db_session):
    for i in range(25):
        cid = f"co-{i}"
        pid = f"pr-{i}"
        _make_company(db_session, cid, headcount=50, city="Pune")
        _make_prospect(db_session, pid, cid, full_name=f"Person {i}")
    db_session.commit()

    result = _run(db_session)

    assert result.batch_size == 20
    assert result.queued_remaining == 5
    assert len(result.qualified_ids) == 20

    still_ingested = db_session.scalars(
        select(Prospect).where(Prospect.status == ProspectStatus.INGESTED)
    ).all()
    assert len(still_ingested) == 5  # not lost, just left for the next run
    # Never evaluated at all -- no reason recorded, distinct from a real disqualification.
    assert all(p.qualification_reason is None for p in still_ingested)


def test_qualify_batch_cap_is_a_true_short_circuit_even_for_failing_candidates(db_session):
    """Candidates beyond the cap are never evaluated, even ones that would
    fail a check -- proving this is a real short-circuit, not "evaluate
    everything, then only mark qualifications up to the cap"."""
    for i in range(20):
        cid = f"co-pass-{i}"
        pid = f"pr-pass-{i}"
        _make_company(db_session, cid, headcount=50, city="Pune")
        _make_prospect(db_session, pid, cid, full_name=f"Pass {i}")
    # These would fail (bad city) if ever evaluated.
    for i in range(3):
        cid = f"co-fail-{i}"
        pid = f"pr-fail-{i}"
        _make_company(db_session, cid, headcount=50, city="Mumbai")
        _make_prospect(db_session, pid, cid, full_name=f"Fail {i}")
    db_session.commit()

    result = _run(db_session)

    assert result.batch_size == 20
    assert result.disqualified_count == 0  # the would-fail candidates were never reached
    assert result.queued_remaining == 3

    untouched = db_session.scalars(
        select(Prospect).where(Prospect.prospect_id.like("pr-fail-%"))
    ).all()
    assert len(untouched) == 3
    for p in untouched:
        assert p.status == ProspectStatus.INGESTED
        assert p.qualification_reason is None
