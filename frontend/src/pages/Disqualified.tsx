import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getDisqualified } from "../api/client";
import HookStrengthBadge from "../components/HookStrengthBadge";
import { EmptyState, ErrorBanner, Spinner } from "../components/Feedback";

const STAGE_LABELS: Record<string, string> = {
  QUALIFICATION: "Dropped at qualification",
  RESEARCH: "No usable hook found",
  EMAIL_GENERATION: "Findings too thin for an email",
};

export default function Disqualified() {
  const query = useQuery({
    queryKey: ["disqualified"],
    queryFn: getDisqualified,
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Disqualified</h1>
        <p className="text-sm text-slate-500 mt-1">
          Prospects that dropped out of the pipeline, and why — whether they
          failed intake qualification (headcount, location, exclusion list,
          duplicate), the research agent found no usable hook, or the
          findings were too thin to write a grounded email. A healthy
          disqualification rate here means the system is being honest about
          weak fit or weak evidence, not that it's failing.
        </p>
      </div>

      {query.isLoading && (
        <div className="text-sm text-slate-500 flex items-center gap-2">
          <Spinner /> Loading…
        </div>
      )}
      {query.isError && (
        <ErrorBanner message="Could not load disqualified prospects (is the backend running?)." />
      )}
      {query.data && query.data.length === 0 && (
        <EmptyState message="No disqualified prospects yet." />
      )}

      <div className="space-y-3">
        {query.data?.map((item) => (
          <div key={item.prospect_id} className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <Link
                    to={`/prospects/${item.prospect_id}`}
                    className="font-semibold text-brand-700 hover:underline"
                  >
                    {item.full_name}
                  </Link>
                  {item.hook_strength !== null && (
                    <HookStrengthBadge hookStrength={item.hook_strength} />
                  )}
                </div>
                <div className="text-sm text-slate-500">{item.company_name}</div>
              </div>
              <span className="inline-flex items-center rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 whitespace-nowrap">
                {STAGE_LABELS[item.stage] ?? item.stage}
              </span>
            </div>

            {item.stage === "QUALIFICATION" && item.qualification_reason && (
              <div className="mt-2 text-sm text-slate-600">
                <span className="font-medium text-slate-700">Reason:</span>{" "}
                {item.qualification_reason}
              </div>
            )}

            {item.stage === "RESEARCH" && (
              <>
                {item.terminal_reason && (
                  <div className="mt-2 text-sm text-slate-600">
                    <span className="font-medium text-slate-700">
                      Terminal reason:
                    </span>{" "}
                    {item.terminal_reason}
                  </div>
                )}
                {item.agent_notes && (
                  <div className="mt-1 text-sm text-slate-500 whitespace-pre-wrap">
                    <span className="font-medium text-slate-600">
                      Agent notes:
                    </span>{" "}
                    {item.agent_notes}
                  </div>
                )}
              </>
            )}

            {item.stage === "EMAIL_GENERATION" && item.email_disqualify_reason && (
              <div className="mt-2 text-sm text-slate-600">
                <span className="font-medium text-slate-700">Reason:</span>{" "}
                {item.email_disqualify_reason}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
