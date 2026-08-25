// Hook strength rubric (0-3), per the research agent's scoring:
//   0 = no basis found (nothing useful)
//   1 = generic industry facts only
//   2 = one specific verifiable fact (a usable hook)
//   3 = a fact that plausibly connects to what Gunadhya does (strong hook)

const RUBRIC: Record<number, { label: string; cls: string }> = {
  0: { label: "No basis", cls: "bg-slate-100 text-slate-600 border-slate-300" },
  1: { label: "Generic", cls: "bg-amber-100 text-amber-800 border-amber-300" },
  2: { label: "Specific hook", cls: "bg-sky-100 text-sky-800 border-sky-300" },
  3: { label: "Strong hook", cls: "bg-emerald-100 text-emerald-800 border-emerald-300" },
};

export default function HookStrengthBadge({
  hookStrength,
  showRubricLabel = true,
}: {
  hookStrength: number | null | undefined;
  showRubricLabel?: boolean;
}) {
  if (hookStrength === null || hookStrength === undefined) {
    return (
      <span className="inline-flex items-center rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-400">
        n/a
      </span>
    );
  }

  const entry = RUBRIC[hookStrength] ?? {
    label: `score ${hookStrength}`,
    cls: "bg-slate-100 text-slate-600 border-slate-300",
  };

  return (
    <span
      title="Hook strength: 0=no basis, 1=generic, 2=specific hook, 3=strong hook"
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${entry.cls}`}
    >
      <span>{hookStrength}/3</span>
      {showRubricLabel && <span className="font-normal">· {entry.label}</span>}
    </span>
  );
}
