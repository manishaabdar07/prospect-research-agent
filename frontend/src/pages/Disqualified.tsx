import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getDisqualified } from "../api/client";
import HookStrengthBadge from "../components/HookStrengthBadge";
import { EmptyState, ErrorBanner, Spinner } from "../components/Feedback";

export default function Disqualified() {
  const query = useQuery({
    queryKey: ["disqualified"],
    queryFn: getDisqualified,
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">
          Disqualified — agent found no usable hook (this is expected and
          correct)
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          These prospects scored below the hook-strength threshold (fewer
          than 2 out of 3): the research agent could not find a specific,
          verifiable fact worth building outreach on. A high disqualification
          rate means the system is being honest about weak evidence, not
          that it's failing — sending a generic email is worse than sending
          none.
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
                  <HookStrengthBadge hookStrength={item.hook_strength} />
                </div>
                <div className="text-sm text-slate-500">{item.company_name}</div>
              </div>
            </div>
            <div className="mt-2 text-sm text-slate-600">
              <span className="font-medium text-slate-700">
                Terminal reason:
              </span>{" "}
              {item.terminal_reason}
            </div>
            {item.agent_notes && (
              <div className="mt-1 text-sm text-slate-500 whitespace-pre-wrap">
                <span className="font-medium text-slate-600">
                  Agent notes:
                </span>{" "}
                {item.agent_notes}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
