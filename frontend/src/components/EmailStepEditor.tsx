import type { EmailStep } from "../api/types";

const PURPOSE_LABELS: Record<string, string> = {
  GIVE: "Give (value-first, no ask)",
  ASK: "Ask (requests a reply / meeting)",
};

/** Read-only display of a 3-step email sequence, e.g. on the prospect detail page. */
export function EmailStepView({ step }: { step: EmailStep }) {
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
            {step.step}
          </span>
          <span className="text-sm font-semibold text-slate-800">
            Send after day {step.send_after_days}
          </span>
        </div>
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
            step.purpose === "ASK"
              ? "bg-purple-50 text-purple-700 border-purple-200"
              : "bg-teal-50 text-teal-700 border-teal-200"
          }`}
        >
          {PURPOSE_LABELS[step.purpose] ?? step.purpose}
        </span>
      </div>
      <div className="mb-2">
        <div className="label">Subject</div>
        <div className="text-sm text-slate-900 font-medium">{step.subject}</div>
      </div>
      <div>
        <div className="label">Body</div>
        <div className="text-sm text-slate-700 whitespace-pre-wrap">{step.body}</div>
      </div>
    </div>
  );
}

/** Editable form for one email step, used in the Review Queue edit flow. */
export function EmailStepEditorForm({
  step,
  onChange,
}: {
  step: EmailStep;
  onChange: (next: EmailStep) => void;
}) {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-800">
          Step {step.step} · send after day {step.send_after_days} ·{" "}
          {PURPOSE_LABELS[step.purpose] ?? step.purpose}
        </span>
      </div>
      <div>
        <label className="label" htmlFor={`subject-${step.step}`}>
          Subject
        </label>
        <input
          id={`subject-${step.step}`}
          className="input"
          value={step.subject}
          onChange={(e) => onChange({ ...step, subject: e.target.value })}
        />
      </div>
      <div>
        <label className="label" htmlFor={`body-${step.step}`}>
          Body
        </label>
        <textarea
          id={`body-${step.step}`}
          className="input min-h-[120px] resize-y"
          value={step.body}
          onChange={(e) => onChange({ ...step, body: e.target.value })}
        />
      </div>
    </div>
  );
}
