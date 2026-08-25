import { EVIDENCE_SLOTS, type Finding } from "../api/types";

const SLOT_LABELS: Record<string, string> = {
  WHAT_THEY_MAKE: "What they make",
  CHANGE_SIGNAL: "Change signal",
  TECH_OPS_SIGNAL: "Tech / ops signal",
  HR_SIGNAL: "HR signal",
  PERSON_SIGNAL: "Person signal",
};

function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.max(0, Math.min(1, confidence)) * 100;
  const color =
    confidence >= 0.7
      ? "bg-emerald-500"
      : confidence >= 0.4
      ? "bg-amber-500"
      : "bg-red-500";
  return (
    <div className="flex items-center gap-2 min-w-[84px]">
      <div className="h-1.5 w-14 rounded-full bg-slate-200 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 tabular-nums">
        {confidence.toFixed(2)}
      </span>
    </div>
  );
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Findings grouped by the 5 evidence slots. Empty slots are shown explicitly
 * (per spec: "clearly show which slots are empty") rather than omitted.
 * When `claimsUsed` is provided (from the synthesis draft), findings referenced
 * by the draft get a small "used in draft" chip so a reviewer can cross-check
 * that the note/emails are grounded in cited findings.
 */
export default function FindingsTable({
  findings,
  slotsEmpty,
  claimsUsed,
}: {
  findings: Finding[];
  slotsEmpty?: string[];
  claimsUsed?: string[];
}) {
  const usedSet = new Set(claimsUsed ?? []);
  const bySlot = new Map<string, Finding[]>();
  for (const f of findings) {
    const list = bySlot.get(f.slot) ?? [];
    list.push(f);
    bySlot.set(f.slot, list);
  }
  const emptySet = new Set(
    slotsEmpty ?? EVIDENCE_SLOTS.filter((s) => !bySlot.has(s))
  );

  return (
    <div className="space-y-5">
      {EVIDENCE_SLOTS.map((slot) => {
        const items = bySlot.get(slot) ?? [];
        const isEmpty = emptySet.has(slot) || items.length === 0;
        return (
          <div key={slot}>
            <div className="flex items-center gap-2 mb-1.5">
              <h4 className="text-sm font-semibold text-slate-800">
                {SLOT_LABELS[slot] ?? slot}
              </h4>
              <span className="text-[10px] uppercase tracking-wide text-slate-400">
                {slot}
              </span>
              {isEmpty && (
                <span className="ml-auto inline-flex items-center rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-xs text-slate-500">
                  empty — nothing found
                </span>
              )}
            </div>
            {isEmpty ? (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-400">
                No finding recorded for this slot.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-md border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-slate-500 w-16">
                        ID
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-slate-500">
                        Claim
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-slate-500">
                        Source
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-slate-500">
                        Retrieved
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-slate-500">
                        Confidence
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {items.map((f) => (
                      <tr key={f.finding_id}>
                        <td className="px-3 py-2 align-top">
                          <span
                            className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-mono ${
                              usedSet.has(f.finding_id)
                                ? "bg-brand-100 text-brand-800"
                                : "bg-slate-100 text-slate-500"
                            }`}
                            title={
                              usedSet.has(f.finding_id)
                                ? "Used in synthesized draft"
                                : f.finding_id
                            }
                          >
                            {f.finding_id}
                          </span>
                        </td>
                        <td className="px-3 py-2 align-top text-slate-800 max-w-md">
                          {f.claim}
                          {usedSet.has(f.finding_id) && (
                            <span className="ml-2 inline-flex items-center rounded-full bg-brand-50 border border-brand-200 px-1.5 py-0.5 text-[10px] font-medium text-brand-700 align-middle">
                              used in draft
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <a
                            href={f.source_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-brand-600 hover:underline break-all"
                          >
                            {hostnameOf(f.source_url)}
                          </a>
                        </td>
                        <td className="px-3 py-2 align-top text-slate-500 whitespace-nowrap">
                          {f.retrieved_at
                            ? new Date(f.retrieved_at).toLocaleDateString()
                            : "—"}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <ConfidenceBar confidence={f.confidence} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
