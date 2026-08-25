import type { ProspectStatus } from "../api/types";

const STYLES: Record<string, string> = {
  INGESTED: "bg-slate-100 text-slate-700 border-slate-300",
  QUALIFIED: "bg-sky-100 text-sky-800 border-sky-300",
  RESEARCHING: "bg-amber-100 text-amber-800 border-amber-300",
  RESEARCHED: "bg-indigo-100 text-indigo-800 border-indigo-300",
  DISQUALIFIED: "bg-slate-200 text-slate-600 border-slate-300",
  SYNTHESIZED: "bg-purple-100 text-purple-800 border-purple-300",
  RENDERED: "bg-teal-100 text-teal-800 border-teal-300",
  APPROVED: "bg-emerald-100 text-emerald-800 border-emerald-300",
  EDITED: "bg-cyan-100 text-cyan-800 border-cyan-300",
  REJECTED: "bg-red-100 text-red-800 border-red-300",
};

export default function StatusBadge({ status }: { status: ProspectStatus | string }) {
  const cls = STYLES[status] ?? "bg-slate-100 text-slate-700 border-slate-300";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${cls}`}
    >
      {status}
    </span>
  );
}
