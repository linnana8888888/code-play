import { useEffect, useState } from "react";
import type { Task, ModelOption } from "../../types/api";
import { getAvailableModels, patchTask, cancelTask } from "../../api/client";
import BlockedTaskActions from "./BlockedTaskActions";

function isOrphaned(task: Task, allTasks: Task[]): boolean {
  if (task.status !== "pending" && task.status !== "assigned") return false;
  if (!task.depends_on?.length) return false;
  return task.depends_on.some((depId) => {
    const dep = allTasks.find((t) => t.id === depId);
    return dep && (dep.status === "failed" || dep.status === "blocked");
  });
}

const columns: { key: Task["status"]; label: string; accent: string }[] = [
  { key: "pending", label: "Pending", accent: "#c37d0d" },
  { key: "assigned", label: "Assigned", accent: "#1e40af" },
  { key: "running", label: "Running", accent: "var(--color-accent-hover)" },
  { key: "blocked", label: "Blocked", accent: "var(--color-danger)" },
  { key: "completed", label: "Done", accent: "var(--color-accent-hover)" },
];

function authorBadge(createdBy?: string | null) {
  if (!createdBy || createdBy === "human") return { label: "human", cls: "badge-blocked" };
  if (createdBy.startsWith("pipeline:")) return { label: "pipeline", cls: "badge-assigned" };
  return { label: "agent", cls: "badge-running" };
}

interface Props {
  tasks: Task[];
  onCreate: () => void;
  onRetried?: () => void;
}

export default function TaskBoard({ tasks, onCreate, onRetried }: Props) {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    getAvailableModels().then(setModels).catch(() => {});
  }, []);

  async function onModelChange(task: Task, value: string) {
    setSaving(task.id);
    try {
      await patchTask(task.id, { model_override: value || null });
    } catch (e) {
      console.error("patchTask failed", e);
    } finally {
      setSaving(null);
    }
  }

  const editableStatuses: Task["status"][] = ["pending", "assigned", "blocked"];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[20px] font-semibold tight-heading">Task Board</h2>
        <button onClick={onCreate} className="btn-primary">
          + New Task
        </button>
      </div>
      <div className="grid grid-cols-5 gap-3">
        {columns.map((col) => {
          const items = tasks.filter((t) => t.status === col.key);
          return (
            <div
              key={col.key}
              className="rounded-2xl border border-border bg-bg-card p-4"
              style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px", borderTop: `2px solid ${col.accent}` }}
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="mono-label">{col.label}</h3>
                <span className="mono-label" style={{ fontSize: "11px" }}>{items.length}</span>
              </div>
              <div className="space-y-2">
                {items.map((t) => {
                  const badge = authorBadge(t.created_by);
                  const orphan = isOrphaned(t, tasks);
                  return (
                    <div key={t.id} className={`rounded-xl border p-3 ${orphan ? "border-warning/50 bg-warning/5" : "border-border bg-bg-subtle"}`}>
                      <div className="flex items-start justify-between gap-1">
                        <p className="text-sm font-medium leading-tight">{t.title}</p>
                        {orphan && (
                          <span className="shrink-0 rounded-md bg-warning/20 px-1.5 py-0.5 text-[9px] font-semibold text-warning">
                            ORPHANED
                          </span>
                        )}
                      </div>
                      {t.assigned_to && (
                        <p className="mt-1 truncate text-[11px] text-text-muted" style={{ fontFamily: "var(--font-mono)" }}>
                          → {t.assigned_to}
                        </p>
                      )}
                      {models.length > 0 && (
                        <div className="mt-2">
                          {editableStatuses.includes(t.status) ? (
                            <select
                              value={t.model_override ?? ""}
                              disabled={saving === t.id}
                              onChange={(e) => onModelChange(t, e.target.value)}
                              className="w-full rounded-lg border border-border bg-white px-2 py-1 text-[10px] text-text-muted outline-none hover:border-accent"
                              title="Per-task LLM override. Blank = agent default."
                            >
                              <option value="">agent default</option>
                              {models.map((m) => (
                                <option key={m.id} value={m.id}>
                                  {m.label}
                                  {m.output_per_1m > 0 ? ` · $${m.output_per_1m}/1M out` : " · free"}
                                </option>
                              ))}
                            </select>
                          ) : t.model_override ? (
                            <p className="truncate text-[10px] text-text-muted" title={t.model_override}>
                              {models.find((m) => m.id === t.model_override)?.label ?? t.model_override}
                            </p>
                          ) : null}
                        </div>
                      )}
                      <div className="mt-2 flex items-center justify-between text-[10px] text-text-muted">
                        <span className={`badge ${badge.cls}`} style={{ fontSize: "9px" }}>{badge.label}</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>P{t.priority}</span>
                      </div>
                      {orphan && (
                        <div className="mt-2">
                          <button
                            onClick={async () => { await cancelTask(t.id, true); onRetried?.(); }}
                            className="rounded-lg border border-warning/40 px-2 py-0.5 text-[10px] text-warning hover:bg-warning/10"
                          >
                            Cancel cascade
                          </button>
                        </div>
                      )}
                      {col.key === "blocked" && (
                        <div className="mt-2">
                          <BlockedTaskActions task={t} onRetried={onRetried} compact />
                        </div>
                      )}
                    </div>
                  );
                })}
                {items.length === 0 && (
                  <p className="py-4 text-center text-xs text-text-subtle">Empty</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
