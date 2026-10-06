// Types matching the Prospect Research Agent backend API contract exactly.
// Keep field names identical to the backend response shapes — do not "improve" casing.

export type ProspectStatus =
  | "INGESTED"
  | "QUALIFIED"
  | "DISQUALIFIED"
  | "RESEARCH_PENDING"
  | "RESEARCHING"
  | "RESEARCH_COMPLETED"
  | "EMAIL_DRAFTED"
  | "EMAIL_SENT"
  | "ERROR";

export const PROSPECT_STATUSES: ProspectStatus[] = [
  "INGESTED",
  "QUALIFIED",
  "DISQUALIFIED",
  "RESEARCH_PENDING",
  "RESEARCHING",
  "RESEARCH_COMPLETED",
  "EMAIL_DRAFTED",
  "EMAIL_SENT",
  "ERROR",
];

export type EvidenceSlot =
  | "WHAT_THEY_MAKE"
  | "CHANGE_SIGNAL"
  | "TECH_OPS_SIGNAL"
  | "HR_SIGNAL"
  | "PERSON_SIGNAL";

export const EVIDENCE_SLOTS: EvidenceSlot[] = [
  "WHAT_THEY_MAKE",
  "CHANGE_SIGNAL",
  "TECH_OPS_SIGNAL",
  "HR_SIGNAL",
  "PERSON_SIGNAL",
];

export type RiskFlagType =
  | "STALE_SOURCE"
  | "SINGLE_SOURCE"
  | "LOW_CONFIDENCE"
  | "NAME_COLLISION"
  | "NO_PERSON_SIGNAL";

// ---- 1. POST /ingest ----
export interface IngestRejectedRow {
  row: number;
  reason: string;
}

export interface IngestResponse {
  ingested: number;
  rejected: IngestRejectedRow[];
  qualified_count: number;
  disqualified_count: number;
  pipeline_started_count: number;
}

// ---- 2. POST /qualify ----
export interface QualifyResponse {
  qualified: string[];
  disqualified_count: number;
  queued_remaining: number;
  batch_size: number;
}

// ---- 3. GET /prospects ----
export interface ProspectListItem {
  prospect_id: string;
  full_name: string;
  title_raw: string;
  company_name: string;
  city: string;
  role_bucket: string;
  seniority: string;
  status: ProspectStatus;
  hook_strength: number | null;
}

// ---- 4. GET /prospects/{id} ----
export interface Finding {
  finding_id: string;
  slot: EvidenceSlot;
  claim: string;
  source_url: string;
  retrieved_at: string;
  confidence: number;
}

export interface Research {
  findings: Finding[];
  slots_filled: EvidenceSlot[];
  slots_empty: EvidenceSlot[];
  hook_strength: number;
  terminal_reason: string;
  agent_notes: string;
  tool_calls_used: number;
}

export type EmailDraftStatus = "DRAFTED" | "SENT";

export interface EmailDraft {
  prospect_id: string;
  subject: string;
  body: string;
  claims_used: string[];
  disqualify: boolean;
  disqualify_reason: string | null;
  needs_human_review: boolean;
  status: EmailDraftStatus;
  created_at: string;
  sent_at: string | null;
}

export interface RiskFlag {
  flag: RiskFlagType | string;
  detail: string;
}

export interface CompanyInfo {
  company_id?: string;
  name?: string;
  domain?: string | null;
  headcount?: number | null;
  city?: string;
  industry_raw?: string;
  [key: string]: unknown;
}

export type CriterionStatus = "MATCHED" | "NOT_MATCHED" | "UNKNOWN";

export interface CriterionResult {
  criterion_name: string;
  criterion_type: string;
  expected: unknown;
  actual: unknown;
  status: CriterionStatus;
  reason: string;
  mandatory: boolean;
}

export interface ProspectInfo {
  prospect_id?: string;
  company_id?: string;
  full_name?: string;
  title_raw?: string;
  role_bucket?: string;
  seniority?: string;
  status?: ProspectStatus;
  linkedin_url?: string | null;
  email?: string | null;
  qualification_reason?: string | null;
  qualified_at?: string | null;
  qualification_details?: CriterionResult[] | null;
  qualification_campaign_id?: number | null;
  qualification_campaign_name?: string | null;
  last_error?: string | null;
  last_error_at?: string | null;
  [key: string]: unknown;
}

// ---- qualification criteria admin ----
export type CriterionType =
  | "RANGE"
  | "LIST"
  | "EXACT_MATCH"
  | "CONTAINS"
  | "BOOLEAN"
  | "EXCLUSION_LIST"
  | "DUPLICATE_CHECK";

export const CRITERION_TYPES: CriterionType[] = [
  "RANGE",
  "LIST",
  "EXACT_MATCH",
  "CONTAINS",
  "BOOLEAN",
  "EXCLUSION_LIST",
  "DUPLICATE_CHECK",
];

export interface QualificationCriterion {
  id: number;
  campaign_id: number;
  name: string;
  criterion_type: CriterionType;
  field: string | null;
  configuration: Record<string, unknown>;
  enabled: boolean;
  mandatory: boolean;
  priority: number;
}

export interface QualificationCriterionCreate {
  name: string;
  criterion_type: CriterionType;
  field: string | null;
  configuration: Record<string, unknown>;
  enabled: boolean;
  mandatory: boolean;
  priority: number;
}

export interface QualificationCriterionUpdate {
  name?: string;
  field?: string | null;
  configuration?: Record<string, unknown>;
  enabled?: boolean;
  mandatory?: boolean;
  priority?: number;
}

// ---- qualification campaigns admin ----
export interface QualificationCampaign {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  min_optional_matches: number | null;
  criteria: QualificationCriterion[];
}

export interface QualificationCampaignCreate {
  name: string;
  description?: string;
  min_optional_matches?: number | null;
}

export interface QualificationCampaignUpdate {
  name?: string;
  description?: string;
  min_optional_matches?: number | null;
}

export interface ProspectDetail {
  prospect: ProspectInfo;
  company: CompanyInfo;
  research: Research | null;
  draft: EmailDraft | null;
  risk_flags: RiskFlag[];
}

// ---- 5 & 6. research + status ----
export interface ResearchStartResponse {
  job_status: "RUNNING";
}

export type ResearchJobStatus = "PENDING" | "RUNNING" | "DONE" | "ERROR";

export interface ResearchStatusResponse {
  status: ResearchJobStatus;
  hook_strength?: number;
  terminal_reason?: string;
  error_message?: string | null;
}

// ---- 7. generate email ----
export interface EmailGenerateResponse {
  status: "DONE" | "DISQUALIFIED" | "NEEDS_REVIEW" | "ERROR";
  draft?: EmailDraft | null;
}

// ---- 8. edit email draft ----
export interface EmailDraftEditRequest {
  subject?: string;
  body?: string;
}

// ---- 9. send email ----
export interface SendEmailResponse {
  status: "SENT";
  sent_at: string;
}

// ---- 10. disqualified ----
export type DisqualificationStage = "QUALIFICATION" | "RESEARCH" | "EMAIL_GENERATION";

export interface DisqualifiedItem {
  prospect_id: string;
  full_name: string;
  company_name: string;
  stage: DisqualificationStage | string;
  qualification_reason: string | null;
  hook_strength: number | null;
  terminal_reason: string | null;
  agent_notes: string | null;
  email_disqualify_reason: string | null;
}

// ---- 11. eval metrics ----
export interface EvalMetrics {
  hook_recall: number | null;
  disqualification_precision: number | null;
  citation_validity: number | null;
}

// ---- 12. run-batch ----
export interface RunBatchResponse {
  started: boolean;
}
