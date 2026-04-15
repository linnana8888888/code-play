import type { Task } from "../../types/api";

const columns: { key: Task["status"]; label: string; color: string }[] = [
  { key: "pending", label: "Pending", color: "border-yellow-500/40" },
  { key: "assigned", label: "Assigned", color: "border-blue-500/40" },
  { key: "running", label: "Running", color: "border-indigo-500/40" },
  { key: "done", label: "Done", color: "border-green-500/40" },
];

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
      <div className="grid grid-cols-4 gap-4">
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
                {items.map((t) => (
                  <div key={t.id} className="rounded-lg border border-border bg-bg p-3">
                    <p className="text-sm font-medium">{t.title}</p>
                    {t.assigned_to && (
                      <p className="mt-1 text-xs text-text-muted">
                        {t.assigned_to}
                      </p>
                    )}
                    <div className="mt-2 flex items-center justify-between text-xs text-text-muted">
                      <span>P{t.priority}</span>
                      <span className="font-mono">{t.id.slice(0, 12)}</span>
                    </div>
                  </div>
                ))}
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
