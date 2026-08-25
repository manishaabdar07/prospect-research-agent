"""Pydantic v2 schemas mirroring app/models.py, plus API request/response shapes.

Kept in one module (vs. a schemas/ package) since the object count is modest
and cross-references (Prospect -> Finding -> Draft) are easier to manage
without circular imports across files.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    EmailPurpose,
    ExclusionType,
    FindingSlot,
    ProspectSource,
    ProspectStatus,
    RejectReason,
    ReviewActionType,
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


class EmailStep(BaseModel):
    step: int = Field(ge=1, le=3)
    send_after_days: int
    subject: str
    body: str
    purpose: EmailPurpose


class OutreachDraftSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prospect_id: str
    connection_note: str = Field(max_length=280)
    email_sequence: list[EmailStep] = Field(default_factory=list)
    claims_used: list[str] = Field(default_factory=list)
    disqualify: bool = False
    disqualify_reason: str | None = None


class RiskFlagSchema(BaseModel):
    flag: str
    detail: str


class ReviewActionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prospect_id: str
    action: ReviewActionType
    reject_reason: RejectReason | None = None
    edited_connection_note: str | None = None
    edited_email_sequence: list[EmailStep] | None = None
    edit_distance: int | None = None
    created_at: datetime


class ExclusionEntrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ExclusionType
    value: str
    reason: str = ""


# --------------------------------------------------------------------------
# API request / response shapes (contract in the spec, matched exactly)
# --------------------------------------------------------------------------


class IngestRejection(BaseModel):
    row: int
    reason: str


class IngestResponse(BaseModel):
    ingested: int
    rejected: list[IngestRejection]


class QualifyResponse(BaseModel):
    qualified: list[str]
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
    draft: OutreachDraftSchema | None = None
    risk_flags: list[RiskFlagSchema] = Field(default_factory=list)
    pdf_available: bool = False


class ResearchStartResponse(BaseModel):
    job_status: str = "RUNNING"


class ResearchStatusResponse(BaseModel):
    status: str  # PENDING | RUNNING | DONE | ERROR
    hook_strength: int | None = None
    terminal_reason: TerminalReason | None = None


class SynthesizeResponse(BaseModel):
    status: str  # DONE | DISQUALIFIED | ERROR
    draft: OutreachDraftSchema | None = None


class RenderResponse(BaseModel):
    pdf_url: str


class ReviewQueueItem(BaseModel):
    prospect_id: str
    full_name: str
    company_name: str
    hook_strength: int | None = None
    pdf_url: str | None = None
    risk_flags: list[RiskFlagSchema] = Field(default_factory=list)


class ApproveResponse(BaseModel):
    status: str = "APPROVED"


class EditRequest(BaseModel):
    edited_connection_note: str | None = None
    edited_email_sequence: list[EmailStep] | None = None


class EditResponse(BaseModel):
    status: str = "EDITED"
    edit_distance: int


class RejectRequest(BaseModel):
    reason: RejectReason


class RejectResponse(BaseModel):
    status: str = "REJECTED"


class DisqualifiedItem(BaseModel):
    prospect_id: str
    full_name: str
    company_name: str
    hook_strength: int | None = None
    terminal_reason: TerminalReason | None = None
    agent_notes: str | None = None


class EvalMetricsResponse(BaseModel):
    hook_recall: float | None = None
    disqualification_precision: float | None = None
    citation_validity: float | None = None
    avg_edit_distance: float | None = None


class RunBatchResponse(BaseModel):
    started: bool


class QualifyRequest(BaseModel):
    """Empty body per spec (`POST /api/qualify` with body `{}`)."""

    pass


class PipelineRunBatchRequest(BaseModel):
    """Empty body per spec (`POST /api/pipeline/run-batch` with body `{}`)."""

    pass
