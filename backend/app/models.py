"""SQLAlchemy ORM models mirroring the spec's data model exactly.

Judgment calls (documented here, also see README):
- ResearchFindings and EmailDraft are 1:1 with a Prospect (keyed by prospect_id
  as primary key). The spec describes "findings" per-run but does not add a
  research_run_id anywhere in the data model, so a new Stage 3 run REPLACES the
  prior ResearchFindings/Finding rows for that prospect (delete-then-insert),
  and a new Stage 4 run replaces the prior EmailDraft row. This keeps "the
  current state of a prospect" simple to query while still satisfying "one per
  prospect per research run" (only the latest run is retained).
- RiskFlag is NOT a table -- flags are computed at read time in app/risk_flags.py
  from Finding/EmailDraft rows already in the DB. This avoids staleness bugs
  where a persisted flag disagrees with the underlying data after an edit.
- Qualification reasons: Prospect.qualification_reason/qualified_at are set for
  every prospect Stage 2 actually evaluates (pass or fail) so a human can see
  why, not just that. A prospect not yet reached because of the batch cap is
  left with qualification_reason=None -- that's "not yet evaluated," distinct
  from a real disqualification.
- Prospect.last_error/last_error_at are the persisted (not just in-memory)
  record of a background-job crash (Stage 3 research or Stage 4 email
  generation), so ProspectStatus.ERROR survives a server restart and is
  visible across worker processes -- unlike the old in-memory-only
  stage3_agent._job_errors dict, which is now a redundant fast-path only.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class RoleBucket(str, enum.Enum):
    IT = "IT"
    HR = "HR"
    OTHER = "OTHER"


class Seniority(str, enum.Enum):
    HEAD = "HEAD"
    VP = "VP"
    DIRECTOR = "DIRECTOR"
    CXO = "CXO"
    OTHER = "OTHER"


class ProspectSource(str, enum.Enum):
    csv = "csv"
    manual = "manual"


class ProspectStatus(str, enum.Enum):
    INGESTED = "INGESTED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    RESEARCH_PENDING = "RESEARCH_PENDING"
    RESEARCHING = "RESEARCHING"
    RESEARCH_COMPLETED = "RESEARCH_COMPLETED"
    EMAIL_DRAFTED = "EMAIL_DRAFTED"
    EMAIL_SENT = "EMAIL_SENT"
    ERROR = "ERROR"


class FindingSlot(str, enum.Enum):
    WHAT_THEY_MAKE = "WHAT_THEY_MAKE"
    CHANGE_SIGNAL = "CHANGE_SIGNAL"
    TECH_OPS_SIGNAL = "TECH_OPS_SIGNAL"
    HR_SIGNAL = "HR_SIGNAL"
    PERSON_SIGNAL = "PERSON_SIGNAL"


class TerminalReason(str, enum.Enum):
    SUFFICIENT = "SUFFICIENT"
    NO_HOOK = "NO_HOOK"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


class EmailDraftStatus(str, enum.Enum):
    DRAFTED = "DRAFTED"
    SENT = "SENT"


class ExclusionType(str, enum.Enum):
    COMPANY = "COMPANY"
    PROSPECT = "PROSPECT"


# --------------------------------------------------------------------------
# Core entities
# --------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str] = mapped_column(String(128), nullable=False)
    industry_raw: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    prospects: Mapped[list["Prospect"]] = relationship(back_populates="company")


class Prospect(Base):
    __tablename__ = "prospects"

    prospect_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    role_bucket: Mapped[RoleBucket] = mapped_column(Enum(RoleBucket, native_enum=False), nullable=False)
    seniority: Mapped[Seniority] = mapped_column(Enum(Seniority, native_enum=False), nullable=False)
    linkedin_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[ProspectSource] = mapped_column(Enum(ProspectSource, native_enum=False), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    status: Mapped[ProspectStatus] = mapped_column(
        Enum(ProspectStatus, native_enum=False), nullable=False, default=ProspectStatus.INGESTED
    )

    # Stage 2 qualification outcome -- set for every prospect actually
    # evaluated (pass or fail), None if not yet reached (e.g. batch cap).
    qualification_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Persisted crash trace for ProspectStatus.ERROR (Stage 3 or Stage 4
    # background-job failures). See module docstring.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="prospects")
    findings: Mapped[list["Finding"]] = relationship(back_populates="prospect", cascade="all, delete-orphan")
    research: Mapped["ResearchFindings | None"] = relationship(
        back_populates="prospect", uselist=False, cascade="all, delete-orphan"
    )
    draft: Mapped["EmailDraft | None"] = relationship(
        back_populates="prospect", uselist=False, cascade="all, delete-orphan"
    )


class Finding(Base):
    """Atomic evidence unit. Nothing enters a draft that isn't one of these."""

    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.prospect_id"), nullable=False, index=True)
    slot: Mapped[FindingSlot] = mapped_column(Enum(FindingSlot, native_enum=False), nullable=False)
    claim: Mapped[str] = mapped_column(String(600), nullable=False)  # ~30 words soft cap, validated in code
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    prospect: Mapped["Prospect"] = relationship(back_populates="findings")


class ResearchFindings(Base):
    """One row per prospect summarizing the latest Stage 3 research run."""

    __tablename__ = "research_findings"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.prospect_id"), primary_key=True)
    slots_filled: Mapped[list] = mapped_column(JSON, default=list)
    slots_empty: Mapped[list] = mapped_column(JSON, default=list)
    hook_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    terminal_reason: Mapped[TerminalReason] = mapped_column(Enum(TerminalReason, native_enum=False), nullable=False)
    agent_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    prospect: Mapped["Prospect"] = relationship(back_populates="research")


class EmailDraft(Base):
    """Stage 4 output: one grounded outreach email per prospect.

    Single subject+body email per the current spec -- no LinkedIn connection
    note, no multi-step drip sequence (that richer shape existed in a prior
    iteration of this app and was deliberately simplified away).
    """

    __tablename__ = "email_drafts"

    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.prospect_id"), primary_key=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    claims_used: Mapped[list] = mapped_column(JSON, default=list)  # list[str] finding_ids
    disqualify: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disqualify_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[EmailDraftStatus] = mapped_column(
        Enum(EmailDraftStatus, native_enum=False), nullable=False, default=EmailDraftStatus.DRAFTED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    prospect: Mapped["Prospect"] = relationship(back_populates="draft")


class ExclusionEntry(Base):
    """Simple DB-backed exclusion list checked by Stage 2 qualify.

    type=COMPANY -> value matched case-insensitively against Company.name
    type=PROSPECT -> value matched case-insensitively against Prospect.full_name
    Used for "active conversation" / "existing client" / "past client" style
    do-not-contact entries. `reason` is free text describing why.
    """

    __tablename__ = "exclusion_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[ExclusionType] = mapped_column(Enum(ExclusionType, native_enum=False), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CRMTask(Base):
    """Stage 6 Load: v1 CRM task table (see app/crm.py::PostgresCRMAdapter)."""

    __tablename__ = "crm_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_ref: Mapped[str] = mapped_column(ForeignKey("prospects.prospect_id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


__all__ = [
    "RoleBucket",
    "Seniority",
    "ProspectSource",
    "ProspectStatus",
    "FindingSlot",
    "TerminalReason",
    "EmailDraftStatus",
    "ExclusionType",
    "Company",
    "Prospect",
    "Finding",
    "ResearchFindings",
    "EmailDraft",
    "ExclusionEntry",
    "CRMTask",
]
