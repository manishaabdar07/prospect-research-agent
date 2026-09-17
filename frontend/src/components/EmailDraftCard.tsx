import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { sendEmail, updateEmailDraft } from "../api/client";
import type { EmailDraft, ProspectStatus } from "../api/types";
import { ErrorBanner, InfoBanner, Spinner } from "./Feedback";

/** The single email-review card: read-only view, Edit, and a confirmation-
 * gated Send Email action. Sending is never automatic -- the user must open
 * the confirm panel and click a second, explicit "Confirm send" button. */
export default function EmailDraftCard({
  prospectId,
  prospectStatus,
  prospectEmail,
  draft,
}: {
  prospectId: string;
  prospectStatus: ProspectStatus;
  prospectEmail: string | null | undefined;
  draft: EmailDraft;
}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"idle" | "editing" | "confirming-send">("idle");
  const [subject, setSubject] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["prospect", prospectId] });
    queryClient.invalidateQueries({ queryKey: ["prospects"] });
  };

  const currentSubject = subject ?? draft.subject;
  const currentBody = body ?? draft.body;

  const saveMutation = useMutation({
    mutationFn: () => updateEmailDraft(prospectId, { subject: currentSubject, body: currentBody }),
    onSuccess: () => {
      setMode("idle");
      invalidate();
    },
  });

  const sendMutation = useMutation({
    mutationFn: () => sendEmail(prospectId),
    onSuccess: () => {
      setMode("idle");
      invalidate();
    },
  });

  const alreadySent = prospectStatus === "EMAIL_SENT" || draft.status === "SENT";
  const canAct = prospectStatus === "EMAIL_DRAFTED" && !alreadySent;

  return (
    <div className="space-y-3">
      {draft.needs_human_review && (
        <InfoBanner
          message={`This draft needs a closer look before sending: ${
            draft.disqualify_reason ?? "the model flagged it for review."
          }`}
        />
      )}

      <div className="card p-4 space-y-3">
        <div className="flex justify-between gap-2 text-sm">
          <span className="text-slate-500">To</span>
          <span className="text-slate-900 text-right">{prospectEmail ?? "— no email on file —"}</span>
        </div>

        {mode === "editing" ? (
          <>
            <div>
              <label className="label" htmlFor={`subject-${prospectId}`}>
                Subject
              </label>
              <input
                id={`subject-${prospectId}`}
                className="input"
                value={currentSubject}
                onChange={(e) => setSubject(e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor={`body-${prospectId}`}>
                Body
              </label>
              <textarea
                id={`body-${prospectId}`}
                className="input min-h-[160px] resize-y"
                value={currentBody}
                onChange={(e) => setBody(e.target.value)}
              />
            </div>
            {saveMutation.isError && <ErrorBanner message="Failed to save the draft." />}
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-primary"
                disabled={saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
              >
                {saveMutation.isPending && <Spinner className="mr-1.5" />}
                Save
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setSubject(null);
                  setBody(null);
                  setMode("idle");
                }}
              >
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <div>
              <div className="label">Subject</div>
              <div className="text-sm font-medium text-slate-900">{currentSubject}</div>
            </div>
            <div>
              <div className="label">Body</div>
              <div className="text-sm text-slate-700 whitespace-pre-wrap">{currentBody}</div>
            </div>
          </>
        )}
      </div>

      {alreadySent && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Email sent{draft.sent_at ? ` on ${new Date(draft.sent_at).toLocaleString()}` : ""}.
        </div>
      )}

      {canAct && mode !== "editing" && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn-secondary" onClick={() => setMode("editing")}>
            Edit
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => setMode(mode === "confirming-send" ? "idle" : "confirming-send")}
          >
            Send Email
          </button>
        </div>
      )}

      {mode === "confirming-send" && (
        <div className="border-t border-slate-200 pt-3 flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-600">
            Send this email to <span className="font-medium">{prospectEmail}</span>?
          </span>
          <button
            type="button"
            className="btn-primary"
            disabled={sendMutation.isPending}
            onClick={() => sendMutation.mutate()}
          >
            {sendMutation.isPending && <Spinner className="mr-1.5" />}
            Confirm send
          </button>
          <button type="button" className="btn-secondary" onClick={() => setMode("idle")}>
            Cancel
          </button>
        </div>
      )}

      {sendMutation.isError && <ErrorBanner message="Failed to send email." />}
    </div>
  );
}
