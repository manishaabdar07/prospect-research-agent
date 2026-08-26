import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  getPdfUrl,
  getProspect,
  getResearchStatus,
  renderProspect,
  startResearch,
  synthesizeProspect,
} from "../api/client";
import StatusBadge from "../components/StatusBadge";
import HookStrengthBadge from "../components/HookStrengthBadge";
import { RiskFlagList } from "../components/RiskFlagBadge";
import FindingsTable from "../components/FindingsTable";
import { EmailStepView } from "../components/EmailStepEditor";
import { ErrorBanner, InfoBanner, Spinner } from "../components/Feedback";

export default function ProspectDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ["prospect", id],
    queryFn: () => getProspect(id as string),
    enabled: !!id,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["prospect", id] });
    queryClient.invalidateQueries({ queryKey: ["prospects"] });
  };

  const researchMutation = useMutation({
    mutationFn: () => startResearch(id as string),
    onSuccess: async () => {
      setPolling(true);
      setPollError(null);
      invalidate();
      try {
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const s = await getResearchStatus(id as string);
          if (s.status === "DONE" || s.status === "ERROR") {
            if (s.status === "ERROR") {
              setPollError(s.terminal_reason ?? "Research failed.");
            }
            break;
          }
        }
      } catch (e) {
        setPollError(e instanceof Error ? e.message : "Polling failed.");
      } finally {
        setPolling(false);
        invalidate();
      }
    },
  });

  const synthesizeMutation = useMutation({
    mutationFn: () => synthesizeProspect(id as string),
    onSuccess: invalidate,
  });

  const renderMutation = useMutation({
    mutationFn: () => renderProspect(id as string),
    onSuccess: invalidate,
  });

  if (!id) return null;

  if (detailQuery.isLoading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-6">
        <div className="text-sm text-slate-500 flex items-center gap-2">
          <Spinner /> Loading prospect…
        </div>
      </div>
    );
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-6">
        <ErrorBanner message="Could not load this prospect (is the backend running?)." />
      </div>
    );
  }

  const { prospect, company, research, draft, risk_flags, pdf_available } =
    detailQuery.data;
  const status = prospect.status;
  const canResearch = status === "QUALIFIED";
  const canSynthesize = status === "RESEARCHED";
  const canRender =
    status === "SYNTHESIZED" ||
    status === "RENDERED" ||
    status === "APPROVED" ||
    status === "EDITED";

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-semibold text-slate-900">
              {prospect.full_name ?? "Prospect"}
            </h1>
            {status && <StatusBadge status={status} />}
            <HookStrengthBadge hookStrength={research?.hook_strength ?? null} />
          </div>
          <div className="text-sm text-slate-500 mt-1">
            {prospect.title_raw} · {company.name} · {company.city}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canResearch && (
            <button
              type="button"
              className="btn-secondary"
              disabled={researchMutation.isPending || polling}
              onClick={() => researchMutation.mutate()}
            >
              {(researchMutation.isPending || polling) && (
                <Spinner className="mr-1.5" />
              )}
              Research
            </button>
          )}
          {canSynthesize && (
            <button
              type="button"
              className="btn-secondary"
              disabled={synthesizeMutation.isPending}
              onClick={() => synthesizeMutation.mutate()}
            >
              {synthesizeMutation.isPending && <Spinner className="mr-1.5" />}
              Synthesize
            </button>
          )}
          {canRender && (
            <button
              type="button"
              className="btn-secondary"
              disabled={renderMutation.isPending}
              onClick={() => renderMutation.mutate()}
            >
              {renderMutation.isPending && <Spinner className="mr-1.5" />}
              Render PDF
            </button>
          )}
          {pdf_available && (
            <a
              href={getPdfUrl(id)}
              target="_blank"
              rel="noreferrer noopener"
              className="btn-primary"
            >
              Download PDF
            </a>
          )}
        </div>
      </div>

      {pollError && <ErrorBanner message={pollError} />}
      {researchMutation.isError && (
        <ErrorBanner message="Failed to start research." />
      )}
      {synthesizeMutation.isError && (
        <ErrorBanner message="Failed to synthesize." />
      )}
      {renderMutation.isError && <ErrorBanner message="Failed to render PDF." />}

      {risk_flags && risk_flags.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-800 mb-2">
            Risk flags
          </h2>
          <RiskFlagList flags={risk_flags} />
        </section>
      )}

      {/* Company + prospect info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-slate-800 mb-2">Company</h2>
          <dl className="text-sm space-y-1.5">
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">Name</dt>
              <dd className="text-slate-900 text-right">
                {company.name ?? "—"}
              </dd>
            </div>
            {company.industry_raw && (
              <div className="flex justify-between gap-2">
                <dt className="text-slate-500">Industry</dt>
                <dd className="text-slate-900 text-right">{company.industry_raw}</dd>
              </div>
            )}
            {company.city !== undefined && (
              <div className="flex justify-between gap-2">
                <dt className="text-slate-500">City</dt>
                <dd className="text-slate-900 text-right">{String(company.city)}</dd>
              </div>
            )}
            {company.headcount !== undefined && company.headcount !== null && (
              <div className="flex justify-between gap-2">
                <dt className="text-slate-500">Headcount</dt>
                <dd className="text-slate-900 text-right">
                  {String(company.headcount)}
                </dd>
              </div>
            )}
            {company.domain && (
              <div className="flex justify-between gap-2">
                <dt className="text-slate-500">Domain</dt>
                <dd className="text-right">
                  <a
                    href={`https://${company.domain}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-brand-600 hover:underline break-all"
                  >
                    {company.domain}
                  </a>
                </dd>
              </div>
            )}
          </dl>
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-semibold text-slate-800 mb-2">Prospect</h2>
          <dl className="text-sm space-y-1.5">
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">Title</dt>
              <dd className="text-slate-900 text-right">{prospect.title_raw ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">Role bucket</dt>
              <dd className="text-slate-900 text-right">{prospect.role_bucket ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">Seniority</dt>
              <dd className="text-slate-900 text-right">{prospect.seniority ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">Email</dt>
              <dd className="text-slate-900 text-right">{prospect.email ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">LinkedIn</dt>
              <dd className="text-right">
                {prospect.linkedin_url ? (
                  <a
                    href={prospect.linkedin_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-brand-600 hover:underline break-all"
                  >
                    View profile
                  </a>
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
        </section>
      </div>

      {/* Findings — most important section */}
      <section>
        <div className="flex items-center gap-3 mb-2 flex-wrap">
          <h2 className="text-base font-semibold text-slate-900">
            Research findings
          </h2>
          {research && (
            <span className="text-xs text-slate-500">
              {research.tool_calls_used} tool call
              {research.tool_calls_used === 1 ? "" : "s"} used
            </span>
          )}
        </div>
        {!research && (
          <InfoBanner message="No research has been run for this prospect yet." />
        )}
        {research && (
          <>
            <FindingsTable
              findings={research.findings}
              slotsEmpty={research.slots_empty}
              claimsUsed={draft?.claims_used}
            />
            {research.agent_notes && (
              <div className="mt-4 card p-4">
                <h3 className="text-sm font-semibold text-slate-800 mb-1">
                  Agent notes
                </h3>
                <p className="text-sm text-slate-600 whitespace-pre-wrap">
                  {research.agent_notes}
                </p>
              </div>
            )}
            {research.terminal_reason && (
              <div className="mt-2 text-xs text-slate-500">
                Terminal reason: {research.terminal_reason}
              </div>
            )}
          </>
        )}
      </section>

      {/* Draft connection note + email sequence */}
      <section>
        <h2 className="text-base font-semibold text-slate-900 mb-2">
          Draft outreach
        </h2>
        {!draft && (
          <InfoBanner message="No draft synthesized yet. Run Synthesize once research is complete (requires hook strength 2 or 3)." />
        )}
        {draft?.disqualify && (
          <InfoBanner
            message={`Not synthesized — disqualified: ${
              draft.disqualify_reason ?? "insufficient hook strength."
            }`}
          />
        )}
        {draft && !draft.disqualify && (
          <div className="space-y-4">
            <div className="card p-4">
              <h3 className="text-sm font-semibold text-slate-800 mb-2">
                Connection note
              </h3>
              <p className="text-sm text-slate-700 whitespace-pre-wrap">
                {draft.connection_note}
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-2">
                Email sequence
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {draft.email_sequence
                  .slice()
                  .sort((a, b) => a.step - b.step)
                  .map((step) => (
                    <EmailStepView key={step.step} step={step} />
                  ))}
              </div>
            </div>
          </div>
        )}
      </section>

      <div className="text-xs text-slate-400">
        <Link to="/prospects" className="hover:underline">
          &larr; Back to prospects
        </Link>
      </div>
    </div>
  );
}
