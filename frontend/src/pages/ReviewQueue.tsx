import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  approveReviewItem,
  editReviewItem,
  getProspect,
  getReviewQueue,
  rejectReviewItem,
} from "../api/client";
import type { EmailStep, ReviewQueueItem, RejectReason } from "../api/types";
import { REJECT_REASONS } from "../api/types";
import HookStrengthBadge from "../components/HookStrengthBadge";
import { RiskFlagList } from "../components/RiskFlagBadge";
import { EmailStepEditorForm } from "../components/EmailStepEditor";
import { EmptyState, ErrorBanner, Spinner } from "../components/Feedback";

const CONNECTION_NOTE_LIMIT = 280;

function EditForm({
  prospectId,
  onDone,
}: {
  prospectId: string;
  onDone: () => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["prospect", prospectId],
    queryFn: () => getProspect(prospectId),
  });

  const [note, setNote] = useState<string | null>(null);
  const [steps, setSteps] = useState<EmailStep[] | null>(null);
  const [editDistance, setEditDistance] = useState<number | null>(null);

  const editMutation = useMutation({
    mutationFn: () =>
      editReviewItem(prospectId, {
        edited_connection_note: note ?? undefined,
        edited_email_sequence: steps ?? undefined,
      }),
    onSuccess: (res) => {
      setEditDistance(res.edit_distance);
    },
  });

  if (detailQuery.isLoading) {
    return (
      <div className="text-sm text-slate-500 flex items-center gap-2 py-3">
        <Spinner /> Loading draft…
      </div>
    );
  }

  if (detailQuery.isError || !detailQuery.data?.draft) {
    return (
      <ErrorBanner message="Could not load the draft to edit for this prospect." />
    );
  }

  const draft = detailQuery.data.draft;
  const currentNote = note ?? draft.connection_note;
  const currentSteps =
    steps ?? draft.email_sequence.slice().sort((a, b) => a.step - b.step);

  return (
    <div className="space-y-4 border-t border-slate-200 pt-4 mt-3">
      <div>
        <div className="flex items-center justify-between">
          <label className="label" htmlFor={`note-${prospectId}`}>
            Connection note
          </label>
          <span
            className={`text-xs ${
              currentNote.length > CONNECTION_NOTE_LIMIT
                ? "text-red-600 font-medium"
                : "text-slate-400"
            }`}
          >
            {currentNote.length} / {CONNECTION_NOTE_LIMIT}
          </span>
        </div>
        <textarea
          id={`note-${prospectId}`}
          className="input min-h-[90px] resize-y"
          value={currentNote}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      <div className="space-y-3">
        <div className="label mb-0">Email sequence</div>
        {currentSteps.map((step, idx) => (
          <EmailStepEditorForm
            key={step.step}
            step={step}
            onChange={(next) => {
              const base = steps ?? draft.email_sequence.slice().sort((a, b) => a.step - b.step);
              const updated = base.slice();
              updated[idx] = next;
              setSteps(updated);
            }}
          />
        ))}
      </div>

      {editMutation.isError && (
        <ErrorBanner message="Failed to save edit." />
      )}
      {editDistance !== null && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Saved. Edit distance from original draft: {editDistance}
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={editMutation.isPending}
          onClick={() => editMutation.mutate()}
        >
          {editMutation.isPending && <Spinner className="mr-1.5" />}
          Save edit
        </button>
        <button type="button" className="btn-secondary" onClick={onDone}>
          Close
        </button>
      </div>
    </div>
  );
}

function ReviewCard({ item }: { item: ReviewQueueItem }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"idle" | "editing" | "rejecting">("idle");
  const [rejectReason, setRejectReason] = useState<RejectReason>("BAD_FIT");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    queryClient.invalidateQueries({ queryKey: ["prospects"] });
    queryClient.invalidateQueries({ queryKey: ["prospect", item.prospect_id] });
  };

  const approveMutation = useMutation({
    mutationFn: () => approveReviewItem(item.prospect_id),
    onSuccess: invalidate,
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectReviewItem(item.prospect_id, { reason: rejectReason }),
    onSuccess: () => {
      setMode("idle");
      invalidate();
    },
  });

  const approved = approveMutation.isSuccess;
  const rejected = rejectMutation.isSuccess;

  return (
    <div className="card p-5 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              to={`/prospects/${item.prospect_id}`}
              className="text-base font-semibold text-brand-700 hover:underline"
            >
              {item.full_name}
            </Link>
            <HookStrengthBadge hookStrength={item.hook_strength} />
          </div>
          <div className="text-sm text-slate-500">{item.company_name}</div>
        </div>
        <a
          href={item.pdf_url}
          target="_blank"
          rel="noreferrer noopener"
          className="btn-secondary"
        >
          Open PDF
        </a>
      </div>

      {item.risk_flags.length > 0 && <RiskFlagList flags={item.risk_flags} />}

      {/* Lightweight inline PDF preview */}
      <div className="rounded-md border border-slate-200 overflow-hidden bg-slate-50">
        <iframe
          src={item.pdf_url}
          title={`PDF preview for ${item.full_name}`}
          className="w-full h-64"
        />
      </div>

      {approved && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Marked approved. Remember: this tool does not send anything — send
          it yourself from your email or LinkedIn.
        </div>
      )}
      {rejected && (
        <div className="rounded-md border border-slate-300 bg-slate-100 px-3 py-2 text-sm text-slate-700">
          Rejected ({rejectReason}).
        </div>
      )}

      {!approved && !rejected && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-success"
            disabled={approveMutation.isPending}
            title="Marks this draft as reviewed and ready — you still send it yourself"
            onClick={() => approveMutation.mutate()}
          >
            {approveMutation.isPending && <Spinner className="mr-1.5" />}
            Mark approved — you send it yourself
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setMode(mode === "editing" ? "idle" : "editing")}
          >
            {mode === "editing" ? "Cancel edit" : "Edit"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setMode(mode === "rejecting" ? "idle" : "rejecting")}
          >
            {mode === "rejecting" ? "Cancel reject" : "Reject"}
          </button>
        </div>
      )}

      {approveMutation.isError && <ErrorBanner message="Failed to approve." />}

      {mode === "rejecting" && !rejected && (
        <div className="border-t border-slate-200 pt-3 mt-1 flex flex-wrap items-center gap-2">
          <label className="text-sm text-slate-600" htmlFor={`reason-${item.prospect_id}`}>
            Reason
          </label>
          <select
            id={`reason-${item.prospect_id}`}
            className="input w-auto"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value as RejectReason)}
          >
            {REJECT_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-danger"
            disabled={rejectMutation.isPending}
            onClick={() => rejectMutation.mutate()}
          >
            {rejectMutation.isPending && <Spinner className="mr-1.5" />}
            Confirm reject
          </button>
          {rejectMutation.isError && (
            <span className="text-xs text-red-600">Failed to reject.</span>
          )}
        </div>
      )}

      {mode === "editing" && (
        <EditForm prospectId={item.prospect_id} onDone={() => setMode("idle")} />
      )}
    </div>
  );
}

export default function ReviewQueue() {
  const queueQuery = useQuery({
    queryKey: ["review-queue"],
    queryFn: getReviewQueue,
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Review queue</h1>
        <p className="text-sm text-slate-500 mt-1">
          Every draft below was written by the agent and grounded in cited
          findings, but nothing is sent automatically. Approve marks a draft
          ready — you still send it yourself from your own email or
          LinkedIn.
        </p>
      </div>

      {queueQuery.isLoading && (
        <div className="text-sm text-slate-500 flex items-center gap-2">
          <Spinner /> Loading review queue…
        </div>
      )}
      {queueQuery.isError && (
        <ErrorBanner message="Could not load the review queue (is the backend running?)." />
      )}
      {queueQuery.data && queueQuery.data.length === 0 && (
        <EmptyState message="Nothing waiting for review right now." />
      )}

      <div className="space-y-4">
        {queueQuery.data?.map((item) => (
          <ReviewCard key={item.prospect_id} item={item} />
        ))}
      </div>
    </div>
  );
}
