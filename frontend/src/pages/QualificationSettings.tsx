import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  activateQualificationCampaign,
  createCampaignCriterion,
  createQualificationCampaign,
  deleteQualificationCampaign,
  deleteQualificationCriterion,
  listCampaignCriteria,
  listQualificationCampaigns,
  updateQualificationCampaign,
  updateQualificationCriterion,
} from "../api/client";
import type {
  CriterionType,
  QualificationCampaign,
  QualificationCriterion,
  QualificationCriterionCreate,
} from "../api/types";
import { CRITERION_TYPES } from "../api/types";
import { ErrorBanner, Spinner } from "../components/Feedback";

const FIELD_OPTIONS = [
  { value: "company.headcount", label: "Company headcount" },
  { value: "company.city", label: "Company city" },
  { value: "company.industry_raw", label: "Company industry" },
  { value: "company.domain", label: "Company domain" },
  { value: "prospect.role_bucket", label: "Prospect role bucket" },
  { value: "prospect.seniority", label: "Prospect seniority" },
  { value: "prospect.title_raw", label: "Prospect title" },
];

const TYPES_NEEDING_FIELD = new Set<CriterionType>([
  "RANGE",
  "LIST",
  "EXACT_MATCH",
  "CONTAINS",
  "BOOLEAN",
]);

function configSummary(type: CriterionType, config: Record<string, unknown>): string {
  switch (type) {
    case "RANGE":
      return `${config.min ?? "–"} to ${config.max ?? "–"}`;
    case "LIST":
      return Array.isArray(config.allowed_values) ? config.allowed_values.join(", ") : "";
    case "CONTAINS":
      return Array.isArray(config.any_of) ? config.any_of.join(", ") : "";
    case "EXACT_MATCH":
      return String(config.value ?? "");
    case "BOOLEAN":
      return `must be ${String(config.expected ?? true)}`;
    case "EXCLUSION_LIST":
    case "DUPLICATE_CHECK":
      return "(no configuration — built-in check)";
    default:
      return "";
  }
}

interface CriterionFormState {
  name: string;
  criterion_type: CriterionType;
  field: string;
  min: string;
  max: string;
  listValue: string; // comma-separated, used for LIST/CONTAINS
  exactValue: string;
  boolExpected: string; // "true" | "false"
  priority: string;
  enabled: boolean;
  mandatory: boolean;
}

const EMPTY_FORM: CriterionFormState = {
  name: "",
  criterion_type: "RANGE",
  field: "company.headcount",
  min: "",
  max: "",
  listValue: "",
  exactValue: "",
  boolExpected: "true",
  priority: "0",
  enabled: true,
  mandatory: true,
};

function formToPayload(form: CriterionFormState): QualificationCriterionCreate {
  let configuration: Record<string, unknown> = {};
  switch (form.criterion_type) {
    case "RANGE":
      configuration = {
        min: form.min === "" ? null : Number(form.min),
        max: form.max === "" ? null : Number(form.max),
      };
      break;
    case "LIST":
      configuration = { allowed_values: form.listValue.split(",").map((v) => v.trim()).filter(Boolean) };
      break;
    case "CONTAINS":
      configuration = { any_of: form.listValue.split(",").map((v) => v.trim()).filter(Boolean) };
      break;
    case "EXACT_MATCH":
      configuration = { value: form.exactValue };
      break;
    case "BOOLEAN":
      configuration = { expected: form.boolExpected === "true" };
      break;
    default:
      configuration = {};
  }
  const needsField = TYPES_NEEDING_FIELD.has(form.criterion_type);
  return {
    name: form.name,
    criterion_type: form.criterion_type,
    field: needsField ? form.field : null,
    configuration,
    enabled: form.enabled,
    mandatory: form.mandatory,
    priority: Number(form.priority) || 0,
  };
}

function criterionToForm(c: QualificationCriterion): CriterionFormState {
  const cfg = c.configuration || {};
  return {
    name: c.name,
    criterion_type: c.criterion_type,
    field: c.field ?? FIELD_OPTIONS[0].value,
    min: cfg.min !== undefined && cfg.min !== null ? String(cfg.min) : "",
    max: cfg.max !== undefined && cfg.max !== null ? String(cfg.max) : "",
    listValue: Array.isArray(cfg.allowed_values)
      ? cfg.allowed_values.join(", ")
      : Array.isArray(cfg.any_of)
        ? (cfg.any_of as string[]).join(", ")
        : "",
    exactValue: cfg.value !== undefined ? String(cfg.value) : "",
    boolExpected: String(cfg.expected ?? true),
    priority: String(c.priority),
    enabled: c.enabled,
    mandatory: c.mandatory,
  };
}

function CriterionFields({
  form,
  onChange,
}: {
  form: CriterionFormState;
  onChange: (next: CriterionFormState) => void;
}) {
  const needsField = TYPES_NEEDING_FIELD.has(form.criterion_type);
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <label className="text-sm text-slate-600">
        Name
        <input
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={form.name}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
        />
      </label>
      <label className="text-sm text-slate-600">
        Type
        <select
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={form.criterion_type}
          onChange={(e) => onChange({ ...form, criterion_type: e.target.value as CriterionType })}
        >
          {CRITERION_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      {needsField && (
        <label className="text-sm text-slate-600 sm:col-span-2">
          Field
          <select
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.field}
            onChange={(e) => onChange({ ...form, field: e.target.value })}
          >
            {FIELD_OPTIONS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      )}

      {form.criterion_type === "RANGE" && (
        <>
          <label className="text-sm text-slate-600">
            Min
            <input
              type="number"
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              value={form.min}
              onChange={(e) => onChange({ ...form, min: e.target.value })}
            />
          </label>
          <label className="text-sm text-slate-600">
            Max
            <input
              type="number"
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              value={form.max}
              onChange={(e) => onChange({ ...form, max: e.target.value })}
            />
          </label>
        </>
      )}

      {(form.criterion_type === "LIST" || form.criterion_type === "CONTAINS") && (
        <label className="text-sm text-slate-600 sm:col-span-2">
          {form.criterion_type === "LIST" ? "Allowed values (comma-separated)" : "Match any of (comma-separated)"}
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.listValue}
            onChange={(e) => onChange({ ...form, listValue: e.target.value })}
            placeholder="Pune, Mumbai, Bangalore"
          />
        </label>
      )}

      {form.criterion_type === "EXACT_MATCH" && (
        <label className="text-sm text-slate-600 sm:col-span-2">
          Value
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.exactValue}
            onChange={(e) => onChange({ ...form, exactValue: e.target.value })}
          />
        </label>
      )}

      {form.criterion_type === "BOOLEAN" && (
        <label className="text-sm text-slate-600">
          Must be
          <select
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.boolExpected}
            onChange={(e) => onChange({ ...form, boolExpected: e.target.value })}
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </label>
      )}

      <label className="text-sm text-slate-600">
        Priority (evaluation order, lower first)
        <input
          type="number"
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={form.priority}
          onChange={(e) => onChange({ ...form, priority: e.target.value })}
        />
      </label>
      <div className="flex items-center gap-4 mt-5">
        <label className="text-sm text-slate-600 flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => onChange({ ...form, enabled: e.target.checked })}
          />
          Enabled
        </label>
        <label className="text-sm text-slate-600 flex items-center gap-2" title="Mandatory criteria must always match; optional criteria count toward the campaign's minimum-optional-matches rule.">
          <input
            type="checkbox"
            checked={form.mandatory}
            onChange={(e) => onChange({ ...form, mandatory: e.target.checked })}
          />
          Mandatory
        </label>
      </div>
    </div>
  );
}

export default function QualificationSettings() {
  const queryClient = useQueryClient();
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);
  const [newCampaignName, setNewCampaignName] = useState("");
  const [addForm, setAddForm] = useState<CriterionFormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<CriterionFormState>(EMPTY_FORM);

  const campaignsQuery = useQuery({
    queryKey: ["qualification-campaigns"],
    queryFn: listQualificationCampaigns,
  });

  const campaigns = campaignsQuery.data ?? [];

  // Default the selection to the active campaign once campaigns load.
  useEffect(() => {
    if (selectedCampaignId === null && campaigns.length > 0) {
      const active = campaigns.find((c) => c.is_active) ?? campaigns[0];
      setSelectedCampaignId(active.id);
    }
  }, [campaigns, selectedCampaignId]);

  const selectedCampaign: QualificationCampaign | undefined = campaigns.find(
    (c) => c.id === selectedCampaignId
  );

  const criteriaQuery = useQuery({
    queryKey: ["qualification-campaign-criteria", selectedCampaignId],
    queryFn: () => listCampaignCriteria(selectedCampaignId as number),
    enabled: selectedCampaignId !== null,
  });

  const invalidateCriteria = () =>
    queryClient.invalidateQueries({ queryKey: ["qualification-campaign-criteria", selectedCampaignId] });
  const invalidateCampaigns = () => queryClient.invalidateQueries({ queryKey: ["qualification-campaigns"] });

  const createCampaignMutation = useMutation({
    mutationFn: createQualificationCampaign,
    onSuccess: (created) => {
      setNewCampaignName("");
      invalidateCampaigns();
      setSelectedCampaignId(created.id);
    },
  });

  const renameCampaignMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => updateQualificationCampaign(id, { name }),
    onSuccess: invalidateCampaigns,
  });

  const minOptionalMutation = useMutation({
    mutationFn: ({ id, min_optional_matches }: { id: number; min_optional_matches: number | null }) =>
      updateQualificationCampaign(id, { min_optional_matches }),
    onSuccess: invalidateCampaigns,
  });

  const activateMutation = useMutation({
    mutationFn: activateQualificationCampaign,
    onSuccess: invalidateCampaigns,
  });

  const deleteCampaignMutation = useMutation({
    mutationFn: deleteQualificationCampaign,
    onSuccess: () => {
      setSelectedCampaignId(null);
      invalidateCampaigns();
    },
  });

  const createMutation = useMutation({
    mutationFn: (body: QualificationCriterionCreate) =>
      createCampaignCriterion(selectedCampaignId as number, body),
    onSuccess: () => {
      setAddForm(EMPTY_FORM);
      invalidateCriteria();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: QualificationCriterionCreate }) =>
      updateQualificationCriterion(id, body),
    onSuccess: () => {
      setEditingId(null);
      invalidateCriteria();
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      updateQualificationCriterion(id, { enabled }),
    onSuccess: invalidateCriteria,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteQualificationCriterion,
    onSuccess: invalidateCriteria,
  });

  const criteria = criteriaQuery.data ?? [];

  function startEdit(c: QualificationCriterion) {
    setEditingId(c.id);
    setEditForm(criterionToForm(c));
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Qualification campaigns</h1>
        <p className="text-sm text-slate-500 mt-1">
          Save a named set of criteria per campaign, switch which one is active,
          and target a specific campaign for one-off runs — different qualification
          runs can use completely different criteria with no code change. Changes
          to a campaign never affect prospects already qualified under it: each
          prospect keeps a frozen breakdown of exactly what it was checked against.
        </p>
      </div>

      {/* Campaign switcher */}
      <section className="card p-5">
        <h2 className="text-sm font-semibold text-slate-800 mb-3">Campaigns</h2>
        {campaignsQuery.isLoading && (
          <div className="text-sm text-slate-500 flex items-center gap-2">
            <Spinner /> Loading…
          </div>
        )}
        <div className="space-y-2">
          {campaigns.map((c) => (
            <div
              key={c.id}
              className={`flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2.5 cursor-pointer ${
                c.id === selectedCampaignId ? "border-brand-400 bg-brand-50/40" : "border-slate-200"
              }`}
              onClick={() => setSelectedCampaignId(c.id)}
            >
              <div className="flex items-center gap-2">
                <input
                  className="text-sm font-medium text-slate-900 bg-transparent border-none focus:outline-none focus:ring-1 focus:ring-brand-300 rounded px-1"
                  value={c.name}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) =>
                    renameCampaignMutation.mutate({ id: c.id, name: e.target.value })
                  }
                />
                {c.is_active && (
                  <span className="text-xs font-medium text-emerald-700 bg-emerald-50 rounded-full px-2 py-0.5">
                    Active
                  </span>
                )}
                <span className="text-xs text-slate-400">{c.criteria.length} criteria</span>
              </div>
              <div className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                {!c.is_active && (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => activateMutation.mutate(c.id)}
                  >
                    Activate
                  </button>
                )}
                <button
                  type="button"
                  className="text-sm text-red-600 hover:underline disabled:text-slate-300 disabled:no-underline"
                  disabled={c.is_active}
                  title={c.is_active ? "Activate another campaign before deleting this one" : undefined}
                  onClick={() => {
                    if (confirm(`Delete campaign "${c.name}"?`)) {
                      deleteCampaignMutation.mutate(c.id);
                    }
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 mt-3">
          <input
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm flex-1"
            placeholder="New campaign name"
            value={newCampaignName}
            onChange={(e) => setNewCampaignName(e.target.value)}
          />
          <button
            type="button"
            className="btn-primary"
            disabled={!newCampaignName || createCampaignMutation.isPending}
            onClick={() => createCampaignMutation.mutate({ name: newCampaignName })}
          >
            {createCampaignMutation.isPending && <Spinner className="mr-1.5" />}
            New campaign
          </button>
        </div>
      </section>

      {selectedCampaign && (
        <>
          {/* Decision rule for the selected campaign */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-1">
              Decision rule — {selectedCampaign.name}
            </h2>
            <p className="text-xs text-slate-500 mb-3">
              Every mandatory criterion must match. Among optional criteria, at
              least this many must also match (leave blank to require all of them too).
            </p>
            <label className="text-sm text-slate-600 flex items-center gap-2">
              Minimum optional criteria that must match
              <input
                type="number"
                className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                value={selectedCampaign.min_optional_matches ?? ""}
                placeholder="all"
                onChange={(e) =>
                  minOptionalMutation.mutate({
                    id: selectedCampaign.id,
                    min_optional_matches: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
              {minOptionalMutation.isPending && <Spinner />}
            </label>
          </section>

          {/* Existing criteria for the selected campaign */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-3">
              Criteria — {selectedCampaign.name}
            </h2>
            {criteriaQuery.isLoading && (
              <div className="text-sm text-slate-500 flex items-center gap-2">
                <Spinner /> Loading…
              </div>
            )}
            {criteriaQuery.isError && (
              <ErrorBanner message="Could not load this campaign's criteria." />
            )}
            <div className="space-y-3">
              {criteria
                .slice()
                .sort((a, b) => a.priority - b.priority)
                .map((c) =>
                  editingId === c.id ? (
                    <div key={c.id} className="rounded-md border border-brand-200 bg-brand-50/40 p-3">
                      <CriterionFields form={editForm} onChange={setEditForm} />
                      <div className="flex gap-2 mt-3">
                        <button
                          type="button"
                          className="btn-primary"
                          disabled={updateMutation.isPending}
                          onClick={() =>
                            updateMutation.mutate({ id: c.id, body: formToPayload(editForm) })
                          }
                        >
                          {updateMutation.isPending && <Spinner className="mr-1.5" />}
                          Save
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => setEditingId(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      key={c.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-2.5"
                    >
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          {c.priority}. {c.name}{" "}
                          <span className="text-xs text-slate-400 font-normal">
                            ({c.criterion_type}
                            {c.field ? ` · ${c.field}` : ""} ·{" "}
                            {c.mandatory ? "mandatory" : "optional"})
                          </span>
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          {configSummary(c.criterion_type, c.configuration)}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <label className="flex items-center gap-1.5 text-xs text-slate-600">
                          <input
                            type="checkbox"
                            checked={c.enabled}
                            onChange={(e) =>
                              toggleMutation.mutate({ id: c.id, enabled: e.target.checked })
                            }
                          />
                          Enabled
                        </label>
                        <button type="button" className="btn-secondary" onClick={() => startEdit(c)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          className="text-sm text-red-600 hover:underline"
                          onClick={() => {
                            if (confirm(`Delete criterion "${c.name}"?`)) {
                              deleteMutation.mutate(c.id);
                            }
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  )
                )}
              {criteria.length === 0 && !criteriaQuery.isLoading && (
                <div className="text-sm text-slate-500">No criteria configured yet.</div>
              )}
            </div>
          </section>

          {/* Add criterion to the selected campaign */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-3">
              Add a criterion — {selectedCampaign.name}
            </h2>
            <CriterionFields form={addForm} onChange={setAddForm} />
            {createMutation.isError && (
              <div className="mt-3">
                <ErrorBanner message="Failed to create criterion." />
              </div>
            )}
            <button
              type="button"
              className="btn-primary mt-3"
              disabled={!addForm.name || createMutation.isPending}
              onClick={() => createMutation.mutate(formToPayload(addForm))}
            >
              {createMutation.isPending && <Spinner className="mr-1.5" />}
              Add criterion
            </button>
          </section>
        </>
      )}
    </div>
  );
}
