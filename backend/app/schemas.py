"""Pydantic v2 schemas mirroring app/models.py, plus API request/response shapes.

Kept in one module (vs. a schemas/ package) since the object count is modest
and cross-references (Prospect -> Finding -> Draft) are easier to manage
without circular imports across files.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    CriterionType,
    EmailDraftStatus,
    ExclusionType,
    FindingSlot,
    ProspectSource,
    ProspectStatus,
    RoleBucket,
    Seniority,
    TerminalReason,
)

# --------------------------------------------------------------------------
# Core entity mirrors
# --------------------------------------------------------------------------


class CompanySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: str
    name: str
    domain: str | None = None
    headcount: int | None = None
    city: str
    industry_raw: str = ""


class CriterionResultSchema(BaseModel):
    """One row of a prospect's Stage 2 per-criterion breakdown, mirroring
    qualification_engine.CriterionResult exactly (stored as plain JSON on
    Prospect.qualification_details, so this schema is what shapes it back
    out over the API)."""

    criterion_name: str
    criterion_type: str
    expected: Any = None
    actual: Any = None
    status: str  # MATCHED | NOT_MATCHED | UNKNOWN
    reason: str
    mandatory: bool = True


class ProspectSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prospect_id: str
    company_id: str
    full_name: str
    title_raw: str
    role_bucket: RoleBucket
    seniority: Seniority
    linkedin_url: str | None = None
    email: str | None = None
    source: ProspectSource
    ingested_at: datetime
    status: ProspectStatus
    qualification_reason: str | None = None
    qualified_at: datetime | None = None
    qualification_details: list[CriterionResultSchema] | None = None
    qualification_campaign_id: int | None = None
    qualification_campaign_name: str | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None


class FindingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: str
    prospect_id: str
    slot: FindingSlot
    claim: str = Field(max_length=600)
    source_url: str
    retrieved_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)


class ResearchFindingsSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prospect_id: str
    findings: list[FindingSchema] = Field(default_factory=list)
    slots_filled: list[str] = Field(default_factory=list)
    slots_empty: list[str] = Field(default_factory=list)
    hook_strength: int = Field(ge=0, le=3)
    terminal_reason: TerminalReason
    agent_notes: str = ""
    tool_calls_used: int = 0


class EmailDraftSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prospect_id: str
    subject: str = Field(max_length=500)
    body: str
    claims_used: list[str] = Field(default_factory=list)
    disqualify: bool = False
    disqualify_reason: str | None = None
    needs_human_review: bool = False
    status: EmailDraftStatus
    created_at: datetime
    sent_at: datetime | None = None


class RiskFlagSchema(BaseModel):
    flag: str
    detail: str


class ExclusionEntrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ExclusionType
    value: str
    reason: str = ""


class QualificationCriterionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    name: str
    criterion_type: CriterionType
    field: str | None = None
    configuration: dict = Field(default_factory=dict)
    enabled: bool = True
    mandatory: bool = True
    priority: int = 0


class QualificationCriterionCreate(BaseModel):
    name: str
    criterion_type: CriterionType
    field: str | None = None
    configuration: dict = Field(default_factory=dict)
    enabled: bool = True
    mandatory: bool = True
    priority: int = 0


class QualificationCriterionUpdate(BaseModel):
    """All fields optional -- only what's supplied gets patched, including
    enable/disable and mandatory/optional (no separate endpoints for those,
    per project convention)."""

    name: str | None = None
    field: str | None = None
    configuration: dict | None = None
    enabled: bool | None = None
    mandatory: bool | None = None
    priority: int | None = None


class QualificationCampaignSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str = ""
    is_active: bool = False
    min_optional_matches: int | None = None
    criteria: list[QualificationCriterionSchema] = Field(default_factory=list)


class QualificationCampaignCreate(BaseModel):
    name: str
    description: str = ""
    min_optional_matches: int | None = None


class QualificationCampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    min_optional_matches: int | None = None


# --------------------------------------------------------------------------
# API request / response shapes (contract in the spec, matched exactly)
# --------------------------------------------------------------------------


class IngestRejection(BaseModel):
    row: int
    reason: str


class IngestResponse(BaseModel):
    ingested: int
    rejected: list[IngestRejection]
    qualified_count: int
    disqualified_count: int
    pipeline_started_count: int


class QualifyResponse(BaseModel):
    qualified: list[str]
    disqualified_count: int
    queued_remaining: int
    batch_size: int


class ProspectListItem(BaseModel):
    prospect_id: str
    full_name: str
    title_raw: str
    company_name: str
    city: str
    role_bucket: RoleBucket
    seniority: Seniority
    status: ProspectStatus
    hook_strength: int | None = None


class ProspectDetailResponse(BaseModel):
    prospect: ProspectSchema
    company: CompanySchema
    research: ResearchFindingsSchema | None = None
    draft: EmailDraftSchema | None = None
    risk_flags: list[RiskFlagSchema] = Field(default_factory=list)


class ResearchStartResponse(BaseModel):
    job_status: str = "RUNNING"


class ResearchStatusResponse(BaseModel):
    status: str  # PENDING | RUNNING | DONE | ERROR
    hook_strength: int | None = None
    terminal_reason: TerminalReason | None = None
    error_message: str | None = None


class EmailGenerateResponse(BaseModel):
    status: str  # DONE | DISQUALIFIED | NEEDS_REVIEW | ERROR
    draft: EmailDraftSchema | None = None


class EmailDraftEditRequest(BaseModel):
    subject: str | None = None
    body: str | None = None


class SendEmailResponse(BaseModel):
    status: str = "SENT"
    sent_at: datetime


class DisqualifiedItem(BaseModel):
    prospect_id: str
    full_name: str
    company_name: str
    stage: str  # QUALIFICATION | RESEARCH | EMAIL_GENERATION
    qualification_reason: str | None = None
    hook_strength: int | None = None
    terminal_reason: TerminalReason | None = None
    agent_notes: str | None = None
    email_disqualify_reason: str | None = None


class EvalMetricsResponse(BaseModel):
    hook_recall: float | None = None
    disqualification_precision: float | None = None
    citation_validity: float | None = None


class RunBatchResponse(BaseModel):
    started: bool


class QualifyRequest(BaseModel):
    """Body defaults to `{}` (matches the original spec's empty-body
    contract) -- campaign_id optionally targets a specific saved campaign
    for this one call, without changing which campaign is globally active."""

    campaign_id: int | None = None


class PipelineRunBatchRequest(BaseModel):
    """Empty body per spec (`POST /api/pipeline/run-batch` with body `{}`)."""

    pass
