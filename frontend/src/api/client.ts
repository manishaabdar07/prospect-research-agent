// Small typed fetch-based API client for the Prospect Research Agent backend.
// Base URL comes from VITE_API_BASE_URL (see .env.example / .env.development),
// defaulting to http://localhost:8000/api if the env var is somehow unset.

import type {
  DisqualifiedItem,
  EmailDraft,
  EmailDraftEditRequest,
  EmailGenerateResponse,
  EvalMetrics,
  IngestResponse,
  ProspectDetail,
  ProspectListItem,
  ProspectStatus,
  QualificationCampaign,
  QualificationCampaignCreate,
  QualificationCampaignUpdate,
  QualificationCriterion,
  QualificationCriterionCreate,
  QualificationCriterionUpdate,
  QualifyResponse,
  ResearchStartResponse,
  ResearchStatusResponse,
  RunBatchResponse,
  SendEmailResponse,
} from "./types";

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      try {
        body = await res.text();
      } catch {
        body = undefined;
      }
    }
    const message =
      (body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : undefined) ?? `Request failed: ${res.status} ${res.statusText}`;
    throw new ApiError(res.status, message, body);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

function patchJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

function putJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

function del(path: string): Promise<void> {
  return request<void>(path, { method: "DELETE" });
}

// ---- 1. ingest ----
export function ingestCsv(file: File): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<IngestResponse>("/ingest", {
    method: "POST",
    body: form,
  });
}

// ---- 2. qualify ----
export function runQualify(campaignId?: number): Promise<QualifyResponse> {
  return postJson<QualifyResponse>("/qualify", { campaign_id: campaignId ?? null });
}

// ---- 3. list prospects ----
export function listProspects(
  status?: ProspectStatus
): Promise<ProspectListItem[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<ProspectListItem[]>(`/prospects${qs}`);
}

// ---- 4. prospect detail ----
export function getProspect(id: string): Promise<ProspectDetail> {
  return request<ProspectDetail>(`/prospects/${encodeURIComponent(id)}`);
}

// ---- 5. start research ----
export function startResearch(id: string): Promise<ResearchStartResponse> {
  return postJson<ResearchStartResponse>(
    `/prospects/${encodeURIComponent(id)}/research`,
    {}
  );
}

// ---- 6. research status ----
export function getResearchStatus(
  id: string
): Promise<ResearchStatusResponse> {
  return request<ResearchStatusResponse>(
    `/prospects/${encodeURIComponent(id)}/research/status`
  );
}

// ---- 7. generate email ----
export function generateEmail(id: string): Promise<EmailGenerateResponse> {
  return postJson<EmailGenerateResponse>(
    `/prospects/${encodeURIComponent(id)}/generate-email`,
    {}
  );
}

// ---- 8. edit email draft ----
export function updateEmailDraft(
  id: string,
  body: EmailDraftEditRequest
): Promise<EmailDraft> {
  return patchJson<EmailDraft>(
    `/prospects/${encodeURIComponent(id)}/email-draft`,
    body
  );
}

// ---- 9. send email ----
export function sendEmail(id: string): Promise<SendEmailResponse> {
  return postJson<SendEmailResponse>(
    `/prospects/${encodeURIComponent(id)}/send-email`,
    {}
  );
}

// ---- 10. disqualified ----
export function getDisqualified(): Promise<DisqualifiedItem[]> {
  return request<DisqualifiedItem[]>("/disqualified");
}

// ---- 11. eval metrics ----
export function getEvalMetrics(): Promise<EvalMetrics> {
  return request<EvalMetrics>("/eval/metrics");
}

// ---- 12. run full batch ----
export function runBatchPipeline(): Promise<RunBatchResponse> {
  return postJson<RunBatchResponse>("/pipeline/run-batch", {});
}

// ---- qualification campaigns admin ----
export function listQualificationCampaigns(): Promise<QualificationCampaign[]> {
  return request<QualificationCampaign[]>("/qualification-campaigns");
}

export function createQualificationCampaign(
  body: QualificationCampaignCreate
): Promise<QualificationCampaign> {
  return postJson<QualificationCampaign>("/qualification-campaigns", body);
}

export function updateQualificationCampaign(
  id: number,
  body: QualificationCampaignUpdate
): Promise<QualificationCampaign> {
  return putJson<QualificationCampaign>(`/qualification-campaigns/${id}`, body);
}

export function deleteQualificationCampaign(id: number): Promise<void> {
  return del(`/qualification-campaigns/${id}`);
}

export function activateQualificationCampaign(id: number): Promise<QualificationCampaign> {
  return postJson<QualificationCampaign>(`/qualification-campaigns/${id}/activate`, {});
}

// ---- qualification criteria admin (scoped to a campaign) ----
export function listCampaignCriteria(campaignId: number): Promise<QualificationCriterion[]> {
  return request<QualificationCriterion[]>(`/qualification-campaigns/${campaignId}/criteria`);
}

export function createCampaignCriterion(
  campaignId: number,
  body: QualificationCriterionCreate
): Promise<QualificationCriterion> {
  return postJson<QualificationCriterion>(`/qualification-campaigns/${campaignId}/criteria`, body);
}

export function updateQualificationCriterion(
  id: number,
  body: QualificationCriterionUpdate
): Promise<QualificationCriterion> {
  return putJson<QualificationCriterion>(`/qualification-criteria/${id}`, body);
}

export function deleteQualificationCriterion(id: number): Promise<void> {
  return del(`/qualification-criteria/${id}`);
}
