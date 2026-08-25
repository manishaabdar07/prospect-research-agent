import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  getResearchStatus,
  listProspects,
  renderProspect,
  startResearch,
  synthesizeProspect,
} from "../api/client";
import type { ProspectStatus } from "../api/types";
import { PROSPECT_STATUSES } from "../api/types";
import StatusBadge from "../components/StatusBadge";
import HookStrengthBadge from "../components/HookStrengthBadge";
import { EmptyState, ErrorBanner, Spinner } from "../components/Feedback";

const RESEARCHABLE: ProspectStatus[] = ["QUALIFIED"];
const SYNTHESIZABLE: ProspectStatus[] = ["RESEARCHED"];
const RENDERABLE: ProspectStatus[] = ["SYNTHESIZED", "RENDERED", "APPROVED", "EDITED"];

function RowActions({ prospectId, status }: { prospectId: string; status: ProspectStatus }) {
  const queryClient = useQueryClient();
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["prospects"] });
    queryClient.invalidateQueries({ queryKey: ["prospect", prospectId] });
  };

  const researchMutation = useMutation({
    mutationFn: () => startResearch(prospectId),
    onSuccess: async () => {
      setPolling(true);
      setPollError(null);
      invalidate();
      try {
        // Poll research status until DONE/ERROR.
        // A simple bounded poll loop keeps this self-contained per row
        // without introducing a global job-tracking store.
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const s = await getResearchStatus(prospectId);
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
    mutationFn: () => synthesizeProspect(prospectId),
    onSuccess: invalidate,
  });

  const renderMutation = useMutation({
    mutationFn: () => renderProspect(prospectId),
    onSuccess: invalidate,
  });

  const busy =
    researchMutation.isPending ||
    polling ||
    synthesizeMutation.isPending ||
    renderMutation.isPending;

  return (
    <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      {RESEARCHABLE.includes(status) && (
        <button
          type="button"
          className="btn-secondary"
          disabled={busy}
          onClick={() => researchMutation.mutate()}
        >
          {(researchMutation.isPending || polling) && <Spinner className="mr-1.5" />}
          Research
        </button>
      )}
      {status === "RESEARCHING" && (
        <span className="inline-flex items-center gap-1.5 text-xs text-amber-700">
          <Spinner /> researching…
        </span>
      )}
      {SYNTHESIZABLE.includes(status) && (
        <button
          type="button"
          className="btn-secondary"
          disabled={busy}
          onClick={() => synthesizeMutation.mutate()}
        >
          {synthesizeMutation.isPending && <Spinner className="mr-1.5" />}
          Synthesize
        </button>
      )}
      {RENDERABLE.includes(status) && (
        <button
          type="button"
          className="btn-secondary"
          disabled={busy}
          onClick={() => renderMutation.mutate()}
        >
          {renderMutation.isPending && <Spinner className="mr-1.5" />}
          Render PDF
        </button>
      )}
      {pollError && <span className="text-xs text-red-600">{pollError}</span>}
      {researchMutation.isError && (
        <span className="text-xs text-red-600">Failed to start research.</span>
      )}
      {synthesizeMutation.isError && (
        <span className="text-xs text-red-600">Failed to synthesize.</span>
      )}
      {renderMutation.isError && (
        <span className="text-xs text-red-600">Failed to render.</span>
      )}
    </div>
  );
}

export default function ProspectsList() {
  const [statusFilter, setStatusFilter] = useState<ProspectStatus | "">("");

  const prospectsQuery = useQuery({
    queryKey: ["prospects", statusFilter || "all"],
    queryFn: () =>
      listProspects(statusFilter ? (statusFilter as ProspectStatus) : undefined),
  });

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-slate-900">Prospects</h1>
        <div className="flex items-center gap-2">
          <label htmlFor="status-filter" className="text-sm text-slate-600">
            Status
          </label>
          <select
            id="status-filter"
            className="input w-auto"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as ProspectStatus | "")}
          >
            <option value="">All</option>
            {PROSPECT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      {prospectsQuery.isLoading && (
        <div className="text-sm text-slate-500 flex items-center gap-2">
          <Spinner /> Loading prospects…
        </div>
      )}
      {prospectsQuery.isError && (
        <ErrorBanner message="Could not load prospects (is the backend running?)." />
      )}
      {prospectsQuery.data && prospectsQuery.data.length === 0 && (
        <EmptyState message="No prospects match this filter yet." />
      )}

      {prospectsQuery.data && prospectsQuery.data.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Name</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Title</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Company</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">City</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Role bucket</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Seniority</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Status</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Hook</th>
                <th className="px-3 py-2 text-left font-medium text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {prospectsQuery.data.map((p) => (
                <tr
                  key={p.prospect_id}
                  className="hover:bg-slate-50 cursor-pointer"
                >
                  <td className="px-3 py-2">
                    <Link
                      to={`/prospects/${p.prospect_id}`}
                      className="text-brand-700 hover:underline font-medium"
                    >
                      {p.full_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{p.title_raw}</td>
                  <td className="px-3 py-2 text-slate-600">{p.company_name}</td>
                  <td className="px-3 py-2 text-slate-600">{p.city}</td>
                  <td className="px-3 py-2 text-slate-600">{p.role_bucket}</td>
                  <td className="px-3 py-2 text-slate-600">{p.seniority}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="px-3 py-2">
                    <HookStrengthBadge hookStrength={p.hook_strength} showRubricLabel={false} />
                  </td>
                  <td className="px-3 py-2">
                    <RowActions prospectId={p.prospect_id} status={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
