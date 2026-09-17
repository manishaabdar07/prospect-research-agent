import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getResearchStatus, listProspects, startResearch } from "../api/client";
import type { ProspectListItem, ProspectStatus } from "../api/types";
import { PROSPECT_STATUSES } from "../api/types";
import StatusBadge from "../components/StatusBadge";
import HookStrengthBadge from "../components/HookStrengthBadge";
import { EmptyState, ErrorBanner, Spinner } from "../components/Feedback";

const IN_FLIGHT_STATUSES = new Set(["RESEARCH_PENDING", "RESEARCHING"]);

/** The only manual trigger left anywhere in this list: recovering a prospect
 * that hard-crashed (e.g. missing API key at the time it was queued). Every
 * normal-path step (qualify, research, generate email) now starts on its
 * own right after upload. */
function RetryResearchAction({ prospectId }: { prospectId: string }) {
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
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const s = await getResearchStatus(prospectId);
          if (s.status === "DONE" || s.status === "ERROR") {
            if (s.status === "ERROR") {
              setPollError(s.error_message ?? s.terminal_reason ?? "Research failed.");
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

  return (
    <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className="btn-secondary"
        disabled={researchMutation.isPending || polling}
        onClick={() => researchMutation.mutate()}
      >
        {(researchMutation.isPending || polling) && <Spinner className="mr-1.5" />}
        Retry research
      </button>
      {pollError && <span className="text-xs text-red-600">{pollError}</span>}
      {researchMutation.isError && (
        <span className="text-xs text-red-600">Failed to start research.</span>
      )}
    </div>
  );
}

function StatusCell({ status }: { status: ProspectStatus }) {
  if (status === "ERROR") {
    return null; // handled by the Actions column's retry button instead
  }
  if (IN_FLIGHT_STATUSES.has(status)) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-amber-700">
        <Spinner /> in progress…
      </span>
    );
  }
  return null;
}

export default function ProspectsList() {
  const [statusFilter, setStatusFilter] = useState<ProspectStatus | "">("");

  const prospectsQuery = useQuery({
    queryKey: ["prospects", statusFilter || "all"],
    queryFn: () =>
      listProspects(statusFilter ? (statusFilter as ProspectStatus) : undefined),
    refetchInterval: (query) => {
      const data = query.state.data as ProspectListItem[] | undefined;
      const inFlight = data?.some((p) => IN_FLIGHT_STATUSES.has(p.status));
      return inFlight ? 3000 : false;
    },
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

      {statusFilter === "EMAIL_DRAFTED" && (
        <p className="text-sm text-slate-500 -mt-2">
          These are ready for review — open a prospect to edit or send its email.
        </p>
      )}

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
                    {p.status === "ERROR" ? (
                      <RetryResearchAction prospectId={p.prospect_id} />
                    ) : (
                      <StatusCell status={p.status} />
                    )}
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
