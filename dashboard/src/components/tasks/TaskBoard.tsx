import type { Task } from "../../types/api";

const columns: { key: Task["status"]; label: string; color: string }[] = [
  { key: "pending", label: "Pending", color: "border-yellow-500/40" },
  { key: "assigned", label: "Assigned", color: "border-blue-500/40" },
  { key: "running", label: "Running", color: "border-indigo-500/40" },
  { key: "blocked", label: "Blocked", color: "border-red-500/40" },
  { key: "completed", label: "Done", color: "border-green-500/40" },
];

function authorBadge(createdBy?: string | null) {
  if (!createdBy || createdBy === "human") return { label: "human", cls: "bg-slate-500/20 text-slate-300" };
  if (createdBy.startsWith("pipeline:")) return { label: "pipeline", cls: "bg-purple-500/20 text-purple-300" };
  return { label: "agent", cls: "bg-emerald-500/20 text-emerald-300" };
}

interface Props {
  tasks: Task[];
  onCreate: () => void;
}

export default function TaskBoard({ tasks, onCreate }: Props) {
  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Task Board</h2>
        <button
          onClick={onCreate}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
        >
          + New Task
        </button>
      </div>
      <div className="grid grid-cols-5 gap-3">
        {columns.map((col) => {
          const items = tasks.filter((t) => t.status === col.key);
          return (
            <div key={col.key} className={`rounded-xl border-t-2 ${col.color} bg-bg-card p-3`}>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                  {col.label}
                </h3>
                <span className="text-xs text-text-muted">{items.length}</span>
              </div>
              <div className="space-y-2">
                {items.map((t) => {
                  const badge = authorBadge(t.created_by);
                  return (
                    <div key={t.id} className="rounded-lg border border-border bg-bg p-3">
                      <p className="text-sm font-medium leading-tight">{t.title}</p>
                      {t.assigned_to && (
                        <p className="mt-1 text-[11px] text-text-muted truncate">→ {t.assigned_to}</p>
                      )}
                      <div className="mt-2 flex items-center justify-between text-[10px] text-text-muted">
                        <span className={`rounded px-1.5 py-0.5 ${badge.cls}`}>{badge.label}</span>
                        <span>P{t.priority}</span>
                      </div>
                    </div>
                  );
                })}
                {items.length === 0 && (
                  <p className="text-xs text-text-muted/50 text-center py-4">Empty</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
