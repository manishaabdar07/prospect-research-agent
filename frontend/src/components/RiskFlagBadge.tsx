import type { RiskFlag } from "../api/types";

const LABELS: Record<string, string> = {
  STALE_SOURCE: "Stale source",
  SINGLE_SOURCE: "Single source",
  LOW_CONFIDENCE: "Low confidence",
  NAME_COLLISION: "Name collision",
  NO_PERSON_SIGNAL: "No person signal",
};

export default function RiskFlagBadge({ flag }: { flag: RiskFlag }) {
  const label = LABELS[flag.flag] ?? flag.flag;
  return (
    <span
      title={flag.detail}
      className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800"
    >
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-3 w-3 shrink-0">
        <path
          fillRule="evenodd"
          d="M8.257 3.099c.765-1.36 2.72-1.36 3.486 0l6.084 10.82c.75 1.334-.213 2.98-1.742 2.98H3.915c-1.53 0-2.492-1.646-1.743-2.98l6.085-10.82ZM11 14a1 1 0 1 1-2 0 1 1 0 0 1 2 0Zm-.25-6.5a.75.75 0 0 0-1.5 0v3.5a.75.75 0 0 0 1.5 0v-3.5Z"
          clipRule="evenodd"
        />
      </svg>
      {label}
    </span>
  );
}

export function RiskFlagList({ flags }: { flags: RiskFlag[] }) {
  if (!flags || flags.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {flags.map((f, i) => (
        <RiskFlagBadge key={`${f.flag}-${i}`} flag={f} />
      ))}
    </div>
  );
}
