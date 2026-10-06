from __future__ import annotations

from datetime import datetime

from app.models import (
    Company,
    ExclusionEntry,
    ExclusionType,
    Prospect,
    ProspectSource,
    ProspectStatus,
    QualificationCriteria,
    RoleBucket,
    Seniority,
)
from app.stages.qualification_engine import decide, evaluate_prospect


def _company(headcount=50, city="Pune", industry_raw="Manufacturing", domain=None) -> Company:
    return Company(company_id="co-1", name="Acme", domain=domain, headcount=headcount, city=city, industry_raw=industry_raw)


def _prospect(**kwargs) -> Prospect:
    defaults = dict(
        prospect_id="pr-1",
        company_id="co-1",
        full_name="Test Person",
        title_raw="Plant Manager",
        role_bucket=RoleBucket.IT,
        seniority=Seniority.OTHER,
        linkedin_url=None,
        email=None,
        source=ProspectSource.csv,
        ingested_at=datetime.utcnow(),
        status=ProspectStatus.INGESTED,
    )
    defaults.update(kwargs)
    return Prospect(**defaults)


def _criterion(**kwargs) -> QualificationCriteria:
    defaults = dict(field=None, configuration={}, enabled=True, mandatory=True, priority=0)
    defaults.update(kwargs)
    return QualificationCriteria(**defaults)


def test_range_matches_within_bounds():
    company = _company(headcount=50)
    prospect = _prospect()
    criterion = _criterion(name="Headcount", criterion_type="RANGE", field="company.headcount",
                            configuration={"min": 10, "max": 200})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "MATCHED"


def test_range_fails_outside_bounds():
    company = _company(headcount=500)
    prospect = _prospect()
    criterion = _criterion(name="Headcount", criterion_type="RANGE", field="company.headcount",
                            configuration={"min": 10, "max": 200})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "NOT_MATCHED"
    assert "500" in results[0].reason


def test_range_unknown_when_field_missing():
    company = _company(headcount=None)
    prospect = _prospect()
    criterion = _criterion(name="Headcount", criterion_type="RANGE", field="company.headcount",
                            configuration={"min": 10, "max": 200})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "UNKNOWN"


def test_list_matches_case_insensitively():
    company = _company(city="PUNE")
    prospect = _prospect()
    criterion = _criterion(name="City", criterion_type="LIST", field="company.city",
                            configuration={"allowed_values": ["Pune", "Mumbai"]})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "MATCHED"


def test_list_fails_when_not_in_allowed_values():
    company = _company(city="Chennai")
    prospect = _prospect()
    criterion = _criterion(name="City", criterion_type="LIST", field="company.city",
                            configuration={"allowed_values": ["Pune", "Mumbai"]})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "NOT_MATCHED"
    assert "Chennai" in results[0].reason


def test_exact_match():
    company = _company(domain="acme.com")
    prospect = _prospect()
    match = _criterion(name="Domain", criterion_type="EXACT_MATCH", field="company.domain",
                        configuration={"value": "acme.com"})
    mismatch = _criterion(name="Domain", criterion_type="EXACT_MATCH", field="company.domain",
                           configuration={"value": "other.com"})

    assert evaluate_prospect(None, prospect, company, [match])[0].status == "MATCHED"
    assert evaluate_prospect(None, prospect, company, [mismatch])[0].status == "NOT_MATCHED"


def test_contains_matches_any_token():
    company = _company(industry_raw="Auto Components Manufacturing")
    prospect = _prospect()
    criterion = _criterion(name="Industry", criterion_type="CONTAINS", field="company.industry_raw",
                            configuration={"any_of": ["fintech", "auto components"]})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "MATCHED"


def test_contains_unknown_when_field_missing():
    company = _company(industry_raw="")
    prospect = _prospect()
    criterion = _criterion(name="Industry", criterion_type="CONTAINS", field="company.industry_raw",
                            configuration={"any_of": ["fintech"]})

    results = evaluate_prospect(None, prospect, company, [criterion])

    assert results[0].status == "UNKNOWN"


def test_boolean_matches_expected():
    # No boolean field exists on Company/Prospect today -- exercise the
    # evaluator directly the way a future field would use it.
    from app.stages.qualification_engine import _evaluate_boolean

    matched = _evaluate_boolean("Uses Cloud", True, {"expected": True})
    not_matched = _evaluate_boolean("Uses Cloud", False, {"expected": True})
    unknown = _evaluate_boolean("Uses Cloud", None, {"expected": True})

    assert matched.status == "MATCHED"
    assert not_matched.status == "NOT_MATCHED"
    assert unknown.status == "UNKNOWN"


def test_evaluate_prospect_stamps_mandatory_from_criterion():
    company = _company(headcount=50)
    prospect = _prospect()
    mandatory_c = _criterion(name="Headcount", criterion_type="RANGE", field="company.headcount",
                              configuration={"min": 10, "max": 200}, mandatory=True)
    optional_c = _criterion(name="City", criterion_type="LIST", field="company.city",
                             configuration={"allowed_values": ["Pune"]}, mandatory=False)

    results = evaluate_prospect(None, prospect, company, [mandatory_c, optional_c])

    assert results[0].mandatory is True
    assert results[1].mandatory is False


def test_exclusion_list_gate_disqualifies_regardless_of_other_matches(db_session):
    company = _company()
    prospect = _prospect(full_name="Blocked Person")
    db_session.add(company)
    db_session.add(ExclusionEntry(type=ExclusionType.PROSPECT, value="Blocked Person", reason="past client"))
    db_session.commit()

    headcount = _criterion(name="Headcount", criterion_type="RANGE", field="company.headcount",
                            configuration={"min": 10, "max": 200})
    exclusion = _criterion(name="Exclusion List", criterion_type="EXCLUSION_LIST")

    results = evaluate_prospect(db_session, prospect, company, [headcount, exclusion])
    qualified, reason = decide(results, None)

    assert qualified is False
    assert "past client" in reason


def test_duplicate_check_gate(db_session):
    company = _company()
    db_session.add(company)
    old = _prospect(prospect_id="pr-old", status=ProspectStatus.QUALIFIED, linkedin_url="https://linkedin.com/in/same")
    new = _prospect(prospect_id="pr-new", linkedin_url="https://linkedin.com/in/same")
    db_session.add(old)
    db_session.add(new)
    db_session.commit()

    criterion = _criterion(name="Duplicate Check", criterion_type="DUPLICATE_CHECK")
    results = evaluate_prospect(db_session, new, company, [criterion])
    qualified, reason = decide(results, None)

    assert qualified is False
    assert "pr-old" in reason


def test_decide_requires_every_mandatory_criterion_to_match():
    from app.stages.qualification_engine import CriterionResult

    results = [
        CriterionResult("A", "RANGE", None, None, "MATCHED", "ok", mandatory=True),
        CriterionResult("B", "LIST", None, None, "NOT_MATCHED", "B failed", mandatory=True),
    ]

    qualified, reason = decide(results, None)

    assert qualified is False
    assert reason == "B failed"


def test_decide_mandatory_failure_disqualifies_even_with_all_optional_matched():
    from app.stages.qualification_engine import CriterionResult

    results = [
        CriterionResult("A", "RANGE", None, None, "NOT_MATCHED", "A failed", mandatory=True),
        CriterionResult("B", "LIST", None, None, "MATCHED", "ok", mandatory=False),
    ]

    qualified, reason = decide(results, None)

    assert qualified is False
    assert reason == "A failed"


def test_decide_min_optional_matches_passes_with_enough_optional_matches():
    from app.stages.qualification_engine import CriterionResult

    results = [
        CriterionResult("A", "RANGE", None, None, "MATCHED", "ok", mandatory=True),
        CriterionResult("B", "LIST", None, None, "MATCHED", "ok", mandatory=False),
        CriterionResult("C", "EXACT_MATCH", None, None, "NOT_MATCHED", "C failed", mandatory=False),
    ]

    qualified, reason = decide(results, 1)

    assert qualified is True
    assert reason == "Passed all qualification checks."


def test_decide_min_optional_matches_none_requires_all_optional_too():
    from app.stages.qualification_engine import CriterionResult

    results = [
        CriterionResult("A", "RANGE", None, None, "MATCHED", "ok", mandatory=True),
        CriterionResult("B", "LIST", None, None, "MATCHED", "ok", mandatory=False),
        CriterionResult("C", "EXACT_MATCH", None, None, "NOT_MATCHED", "C failed", mandatory=False),
    ]

    qualified, reason = decide(results, None)

    assert qualified is False
    assert reason == "C failed"


def test_min_optional_matches_above_available_optional_count_is_clamped_not_impossible():
    """A campaign where every criterion is mandatory (zero optional) but
    min_optional_matches is still set to some leftover/misconfigured number
    must not become an impossible-to-pass trap -- real bug hit in production:
    a prospect matching 100% of its (all-mandatory) criteria was disqualified
    because min_optional_matches=5 demanded 5 optional matches that could
    never exist."""
    from app.stages.qualification_engine import CriterionResult

    results = [
        CriterionResult("A", "RANGE", None, None, "MATCHED", "ok", mandatory=True),
        CriterionResult("B", "LIST", None, None, "MATCHED", "ok", mandatory=True),
    ]

    qualified, reason = decide(results, 5)

    assert qualified is True
    assert reason == "Passed all qualification checks."


def test_unknown_counts_as_not_matched():
    company = _company(headcount=None)
    prospect = _prospect()
    criterion = _criterion(name="Headcount", criterion_type="RANGE", field="company.headcount",
                            configuration={"min": 10, "max": 200})

    results = evaluate_prospect(None, prospect, company, [criterion])
    qualified, _reason = decide(results, None)

    assert results[0].status == "UNKNOWN"
    assert qualified is False


def test_two_campaigns_produce_independent_results_for_the_same_prospect():
    """Different campaigns checking different criteria against the same
    prospect must not influence each other."""
    company = _company(headcount=50, city="Pune", industry_raw="FinTech")
    prospect = _prospect()

    manufacturing_campaign_criteria = [
        _criterion(name="Headcount Band", criterion_type="RANGE", field="company.headcount",
                   configuration={"min": 10, "max": 200}),
        _criterion(name="City Allowlist", criterion_type="LIST", field="company.city",
                   configuration={"allowed_values": ["Pune"]}),
    ]
    saas_campaign_criteria = [
        _criterion(name="Industry", criterion_type="LIST", field="company.industry_raw",
                   configuration={"allowed_values": ["SaaS", "Software"]}),
    ]

    manufacturing_results = evaluate_prospect(None, prospect, company, manufacturing_campaign_criteria)
    saas_results = evaluate_prospect(None, prospect, company, saas_campaign_criteria)

    manufacturing_qualified, _ = decide(manufacturing_results, None)
    saas_qualified, _ = decide(saas_results, None)

    assert manufacturing_qualified is True
    assert saas_qualified is False
