/**
 * NeedsAttention — top-of-dashboard banner summarising blocked tasks by
 * `failure_category` and exposing inline retry actions. Expands into a list
 * that renders BlockedTaskActions per task so the operator can act without
 * drilling into the board.
 */
import { useMemo, useState } from "react";
import type { FailureCategory, Task } from "../../types/api";
import { cancelBlockedTasks, cancelTask } from "../../api/client";
import BlockedTaskActions from "./BlockedTaskActions";

interface Props {
  tasks: Task[];
  onRetried?: () => void;
}

function isOrphaned(task: Task, allTasks: Task[]): boolean {
  if (task.status !== "pending" && task.status !== "assigned") return false;
  if (!task.depends_on?.length) return false;
  return task.depends_on.some((depId) => {
    const dep = allTasks.find((t) => t.id === depId);
    return dep && (dep.status === "failed" || dep.status === "blocked");
  });
}

const ORDER: FailureCategory[] = [
  "budget_exhausted",
  "transient",
  "spawn",
  "permanent",
];

function labelFor(cat: FailureCategory): string {
  switch (cat) {
    case "budget_exhausted":
      return "budget exhausted";
    case "transient":
      return "provider error";
    case "spawn":
      return "spawn failed";
    default:
      return "config blocked";
  }
}

function toneCls(cat: FailureCategory): string {
  if (cat === "budget_exhausted") return "text-warning";
  if (cat === "transient") return "text-info";
  if (cat === "spawn") return "text-warning";
  return "text-danger";
}

export default function NeedsAttention({ tasks, onRetried }: Props) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [dismissingAll, setDismissingAll] = useState(false);

  async function doDismissAll() {
    setDismissingAll(true);
    try {
      await cancelBlockedTasks();
      onRetried?.();
    } finally {
      setDismissingAll(false);
      setConfirming(false);
    }
  }

  const blocked = useMemo(
    () => tasks.filter((t) => t.status === "blocked"),
    [tasks],
  );

  const orphaned = useMemo(
    () => tasks.filter((t) => isOrphaned(t, tasks)),
    [tasks],
  );

  const [cancellingOrphans, setCancellingOrphans] = useState(false);

  async function doCancelOrphans() {
    setCancellingOrphans(true);
    try {
      for (const t of orphaned) {
        await cancelTask(t.id, true);
      }
      onRetried?.();
    } finally {
      setCancellingOrphans(false);
    }
  }

  const groups = useMemo(() => {
    const out: Record<FailureCategory, Task[]> = {
      budget_exhausted: [],
      transient: [],
      spawn: [],
      permanent: [],
    };
    for (const t of blocked) {
      const cat = (t.result?.failure_category ?? "permanent") as FailureCategory;
      (out[cat] ?? out.permanent).push(t);
    }
    return out;
  }, [blocked]);

  if (blocked.length === 0 && orphaned.length === 0) return null;

  return (
    <div className="rounded-2xl border border-danger/40 bg-danger/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="mono-label text-danger">
            Needs attention
            {blocked.length > 0 && ` · ${blocked.length} blocked`}
            {orphaned.length > 0 && ` · ${orphaned.length} orphaned`}
          </p>
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            {ORDER.map((cat) =>
              groups[cat].length ? (
                <span key={cat} className={toneCls(cat)}>
                  {groups[cat].length} {labelFor(cat)}
                </span>
              ) : null,
            )}
            {orphaned.length > 0 && (
              <span className="text-warning">
                {orphaned.length} orphaned
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {confirming ? (
            <>
              <span className="text-[11px] text-danger">Dismiss {blocked.length} blocked?</span>
              <button
                onClick={doDismissAll}
                disabled={dismissingAll}
                className="rounded-lg bg-danger px-2 py-0.5 text-[11px] font-semibold text-bg hover:bg-danger/90 disabled:opacity-50"
              >
                {dismissingAll ? "Dismissing…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="btn-ghost text-[11px]"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              {orphaned.length > 0 && (
                <button
                  onClick={doCancelOrphans}
                  disabled={cancellingOrphans}
                  className="rounded-lg border border-warning/40 px-2 py-0.5 text-[11px] text-warning hover:bg-warning/10 disabled:opacity-50"
                >
                  {cancellingOrphans ? "Cancelling…" : `Cancel ${orphaned.length} orphaned`}
                </button>
              )}
              {blocked.length > 0 && (
                <button
                  onClick={() => setConfirming(true)}
                  className="rounded-lg border border-danger/40 px-2 py-0.5 text-[11px] text-danger hover:bg-danger/10"
                >
                  Dismiss all
                </button>
              )}
              <button
                onClick={() => setOpen((v) => !v)}
                className="btn-ghost"
                aria-expanded={open}
              >
                {open ? "Hide" : "Review"}
              </button>
            </>
          )}
        </div>
      </div>

      {open && (
        <div className="mt-3 space-y-2">
          {orphaned.length > 0 && (
            <p className="mono-label text-warning text-[10px] mb-1">Orphaned (deps failed/cancelled)</p>
          )}
          {orphaned.map((t) => (
            <div
              key={`orphan-${t.id}`}
              className="rounded-xl border border-warning/30 bg-warning/5 p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{t.title}</p>
                  <p
                    className="mt-0.5 truncate text-[11px] text-text-muted"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {t.id} · orphaned
                  </p>
                </div>
                <button
                  onClick={async () => { await cancelTask(t.id, true); onRetried?.(); }}
                  className="shrink-0 rounded-lg border border-warning/40 px-2 py-0.5 text-[11px] text-warning hover:bg-warning/10"
                >
                  Cancel cascade
                </button>
              </div>
            </div>
          ))}
          {blocked.length > 0 && (
            <p className="mono-label text-danger text-[10px] mb-1 mt-3">Blocked</p>
          )}
          {ORDER.flatMap((cat) =>
            groups[cat].map((t) => (
              <div
                key={t.id}
                className="rounded-xl border border-border bg-white p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{t.title}</p>
                    <p
                      className="mt-0.5 truncate text-[11px] text-text-muted"
                      style={{ fontFamily: "var(--font-mono)" }}
                    >
                      {t.id}
                    </p>
                  </div>
                </div>
                <div className="mt-2">
                  <BlockedTaskActions task={t} onRetried={onRetried} compact />
                </div>
              </div>
            )),
          )}
        </div>
      )}
    </div>
  );
}
