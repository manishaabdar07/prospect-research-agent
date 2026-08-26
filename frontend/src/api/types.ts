// Types matching the Prospect Research Agent backend API contract exactly.
// Keep field names identical to the backend response shapes — do not "improve" casing.

export type ProspectStatus =
  | "INGESTED"
  | "QUALIFIED"
  | "RESEARCHING"
  | "RESEARCHED"
  | "DISQUALIFIED"
  | "SYNTHESIZED"
  | "RENDERED"
  | "APPROVED"
  | "EDITED"
  | "REJECTED";

export const PROSPECT_STATUSES: ProspectStatus[] = [
  "INGESTED",
  "QUALIFIED",
  "RESEARCHING",
  "RESEARCHED",
  "DISQUALIFIED",
  "SYNTHESIZED",
  "RENDERED",
  "APPROVED",
  "EDITED",
  "REJECTED",
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

export type RejectReason =
  | "BAD_FIT"
  | "WEAK_HOOK"
  | "WRONG_FACTS"
  | "TONE"
  | "ALREADY_KNOWN";

export const REJECT_REASONS: RejectReason[] = [
  "BAD_FIT",
  "WEAK_HOOK",
  "WRONG_FACTS",
  "TONE",
  "ALREADY_KNOWN",
];

// ---- 1. POST /ingest ----
export interface IngestRejectedRow {
  row: number;
  reason: string;
}

export interface IngestResponse {
  ingested: number;
  rejected: IngestRejectedRow[];
}

// ---- 2. POST /qualify ----
export interface QualifyResponse {
  qualified: string[];
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

export type EmailPurpose = "GIVE" | "ASK";

export interface EmailStep {
  step: number;
  send_after_days: number;
  subject: string;
  body: string;
  purpose: EmailPurpose;
}

export interface Draft {
  connection_note: string;
  email_sequence: EmailStep[];
  claims_used: string[];
  disqualify: boolean;
  disqualify_reason: string | null;
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
  [key: string]: unknown;
}

export interface ProspectDetail {
  prospect: ProspectInfo;
  company: CompanyInfo;
  research: Research | null;
  draft: Draft | null;
  risk_flags: RiskFlag[];
  pdf_available: boolean;
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
}

// ---- 7. synthesize ----
export interface SynthesizeResponse {
  status: "DONE" | "DISQUALIFIED" | "ERROR";
  draft?: Draft;
}

// ---- 8. render ----
export interface RenderResponse {
  pdf_url: string;
}

// ---- 10. review queue ----
export interface ReviewQueueItem {
  prospect_id: string;
  full_name: string;
  company_name: string;
  hook_strength: number;
  pdf_url: string;
  risk_flags: RiskFlag[];
}

export interface ApproveResponse {
  status: "APPROVED";
}

export interface EditRequest {
  edited_connection_note?: string;
  edited_email_sequence?: EmailStep[];
}

export interface EditResponse {
  status: "EDITED";
  edit_distance: number;
}

export interface RejectRequest {
  reason: RejectReason;
}

export interface RejectResponse {
  status: "REJECTED";
}

// ---- 14. disqualified ----
export interface DisqualifiedItem {
  prospect_id: string;
  full_name: string;
  company_name: string;
  hook_strength: number;
  terminal_reason: string;
  agent_notes: string;
}

// ---- 15. eval metrics ----
export interface EvalMetrics {
  hook_recall: number | null;
  disqualification_precision: number | null;
  citation_validity: number | null;
  avg_edit_distance: number | null;
}

// ---- 16. run-batch ----
export interface RunBatchResponse {
  started: boolean;
}
