import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getEvalMetrics,
  ingestCsv,
  listProspects,
  runBatchPipeline,
  runQualify,
} from "../api/client";
import type { IngestResponse, QualifyResponse } from "../api/types";
import { PROSPECT_STATUSES } from "../api/types";
import { Spinner, ErrorBanner } from "../components/Feedback";
import StatusBadge from "../components/StatusBadge";

function MetricTile({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="text-lg font-semibold text-slate-900">
        {value === null || value === undefined
          ? "not enough data yet"
          : `${(value * 100).toFixed(0)}%`}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const prospectsQuery = useQuery({
    queryKey: ["prospects", "all"],
    queryFn: () => listProspects(),
  });

  const metricsQuery = useQuery({
    queryKey: ["eval-metrics"],
    queryFn: getEvalMetrics,
    retry: false,
  });

  const ingestMutation = useMutation({
    mutationFn: (file: File) => ingestCsv(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
    },
  });

  const qualifyMutation = useMutation({
    mutationFn: runQualify,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
    },
  });

  const runBatchMutation = useMutation({
    mutationFn: runBatchPipeline,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
    },
  });

  const counts = new Map<string, number>();
  for (const p of prospectsQuery.data ?? []) {
    counts.set(p.status, (counts.get(p.status) ?? 0) + 1);
  }
  const total = prospectsQuery.data?.length ?? 0;

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSelectedFile(e.target.files?.[0] ?? null);
  }

  function handleUpload() {
    if (selectedFile) {
      ingestMutation.mutate(selectedFile);
    }
  }

  const ingestResult: IngestResponse | undefined = ingestMutation.data;
  const qualifyResult: QualifyResponse | undefined = qualifyMutation.data;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Pipeline</h1>
        <p className="text-sm text-slate-500 mt-1">
          Upload a prospect CSV, qualify a batch, then run research and
          synthesis per prospect from the Prospects page. This tool never
          sends anything on its own — every outbound email is reviewed and
          sent by a human from the Review Queue.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* CSV upload */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-1">
              1. Ingest prospects
            </h2>
            <p className="text-sm text-slate-500 mb-3">
              Upload a CSV with columns for name, title and company. Rows
              that fail basic cleaning are rejected with a reason and can be
              fixed and re-uploaded.
            </p>
            <div className="flex items-center gap-3">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,text/csv"
                onChange={handleFileChange}
                className="text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
              />
              <button
                type="button"
                className="btn-primary"
                disabled={!selectedFile || ingestMutation.isPending}
                onClick={handleUpload}
              >
                {ingestMutation.isPending && <Spinner className="mr-1.5" />}
                Upload &amp; ingest
              </button>
            </div>

            {ingestMutation.isError && (
              <div className="mt-3">
                <ErrorBanner
                  message={
                    ingestMutation.error instanceof Error
                      ? ingestMutation.error.message
                      : "Failed to ingest CSV."
                  }
                />
              </div>
            )}

            {ingestResult && (
              <div className="mt-4 space-y-2">
                <div className="text-sm text-emerald-700 font-medium">
                  Ingested {ingestResult.ingested} prospect
                  {ingestResult.ingested === 1 ? "" : "s"}.
                </div>
                {ingestResult.rejected.length > 0 && (
                  <div>
                    <div className="text-sm text-slate-600 mb-1">
                      Rejected {ingestResult.rejected.length} row
                      {ingestResult.rejected.length === 1 ? "" : "s"}:
                    </div>
                    <div className="overflow-x-auto rounded-md border border-slate-200">
                      <table className="min-w-full divide-y divide-slate-200 text-sm">
                        <thead className="bg-slate-50">
                          <tr>
                            <th className="px-3 py-1.5 text-left font-medium text-slate-500 w-20">
                              Row
                            </th>
                            <th className="px-3 py-1.5 text-left font-medium text-slate-500">
                              Reason
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 bg-white">
                          {ingestResult.rejected.map((r, i) => (
                            <tr key={i}>
                              <td className="px-3 py-1.5 text-slate-700">
                                {r.row}
                              </td>
                              <td className="px-3 py-1.5 text-slate-700">
                                {r.reason}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Qualify + run batch */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-1">
              2. Qualify a batch
            </h2>
            <p className="text-sm text-slate-500 mb-3">
              Filters and dedupes ingested prospects down to a qualified
              batch (~20) ready for research.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn-primary"
                disabled={qualifyMutation.isPending}
                onClick={() => qualifyMutation.mutate()}
              >
                {qualifyMutation.isPending && <Spinner className="mr-1.5" />}
                Run qualify
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={runBatchMutation.isPending}
                onClick={() => runBatchMutation.mutate()}
                title="Convenience action: runs qualify + research + synthesis + render across the queued batch on the backend"
              >
                {runBatchMutation.isPending && <Spinner className="mr-1.5" />}
                Run full batch pipeline
              </button>
            </div>

            {qualifyMutation.isError && (
              <div className="mt-3">
                <ErrorBanner
                  message={
                    qualifyMutation.error instanceof Error
                      ? qualifyMutation.error.message
                      : "Failed to run qualify."
                  }
                />
              </div>
            )}

            {qualifyResult && (
              <div className="mt-3 text-sm text-slate-700 space-y-0.5">
                <div>
                  Qualified{" "}
                  <span className="font-semibold">
                    {qualifyResult.qualified.length}
                  </span>{" "}
                  prospect{qualifyResult.qualified.length === 1 ? "" : "s"} into
                  this batch (batch size {qualifyResult.batch_size}).
                </div>
                <div className="text-slate-500">
                  {qualifyResult.queued_remaining} prospect
                  {qualifyResult.queued_remaining === 1 ? "" : "s"} still
                  queued for a future batch.
                </div>
              </div>
            )}

            {runBatchMutation.isError && (
              <div className="mt-3">
                <ErrorBanner
                  message={
                    runBatchMutation.error instanceof Error
                      ? runBatchMutation.error.message
                      : "Failed to start batch pipeline."
                  }
                />
              </div>
            )}
            {runBatchMutation.isSuccess && (
              <div className="mt-3 text-sm text-emerald-700">
                {runBatchMutation.data.started
                  ? "Batch pipeline started on the backend. Check the Prospects page for progress."
                  : "Batch pipeline did not start — nothing was queued."}
              </div>
            )}
          </section>

          {/* Status summary */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-3">
              Prospect counts by status
            </h2>
            {prospectsQuery.isLoading && (
              <div className="text-sm text-slate-500 flex items-center gap-2">
                <Spinner /> Loading prospects…
              </div>
            )}
            {prospectsQuery.isError && (
              <ErrorBanner message="Could not load prospects (is the backend running?)." />
            )}
            {prospectsQuery.data && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <div className="rounded-md border border-slate-200 px-3 py-2">
                  <div className="text-xs uppercase tracking-wide text-slate-500">
                    Total
                  </div>
                  <div className="text-lg font-semibold text-slate-900">
                    {total}
                  </div>
                </div>
                {PROSPECT_STATUSES.map((s) => (
                  <div
                    key={s}
                    className="rounded-md border border-slate-200 px-3 py-2 flex items-center justify-between"
                  >
                    <StatusBadge status={s} />
                    <span className="text-lg font-semibold text-slate-900">
                      {counts.get(s) ?? 0}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Eval metrics sidebar */}
        <aside className="lg:col-span-1">
          <section className="card p-5 sticky top-4">
            <h2 className="text-sm font-semibold text-slate-800 mb-1">
              Eval metrics
            </h2>
            <p className="text-xs text-slate-500 mb-3">
              Quality signals for the pipeline. A high disqualification rate
              is expected and healthy — it means the agent is being honest
              about weak or missing evidence rather than fabricating hooks.
            </p>
            {metricsQuery.isLoading && (
              <div className="text-sm text-slate-500 flex items-center gap-2">
                <Spinner /> Loading…
              </div>
            )}
            {metricsQuery.isError && (
              <div className="text-sm text-slate-400">
                Eval metrics unavailable.
              </div>
            )}
            {metricsQuery.data && (
              <div className="grid grid-cols-1 gap-2">
                <MetricTile
                  label="Hook recall"
                  value={metricsQuery.data.hook_recall}
                />
                <MetricTile
                  label="Disqualification precision"
                  value={metricsQuery.data.disqualification_precision}
                />
                <MetricTile
                  label="Citation validity"
                  value={metricsQuery.data.citation_validity}
                />
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="text-xs uppercase tracking-wide text-slate-500">
                    Avg. edit distance
                  </div>
                  <div className="text-lg font-semibold text-slate-900">
                    {metricsQuery.data.avg_edit_distance === null ||
                    metricsQuery.data.avg_edit_distance === undefined
                      ? "not enough data yet"
                      : metricsQuery.data.avg_edit_distance.toFixed(1)}
                  </div>
                </div>
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
