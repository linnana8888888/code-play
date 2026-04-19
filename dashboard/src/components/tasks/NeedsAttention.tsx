/**
 * NeedsAttention — top-of-dashboard banner summarising blocked tasks by
 * `failure_category` and exposing inline retry actions. Expands into a list
 * that renders BlockedTaskActions per task so the operator can act without
 * drilling into the board.
 */
import { useMemo, useState } from "react";
import type { FailureCategory, Task } from "../../types/api";
import BlockedTaskActions from "./BlockedTaskActions";

interface Props {
  tasks: Task[];
  onRetried?: () => void;
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
  const blocked = useMemo(
    () => tasks.filter((t) => t.status === "blocked"),
    [tasks],
  );

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

  if (blocked.length === 0) return null;

  return (
    <div className="rounded-2xl border border-danger/40 bg-danger/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="mono-label text-danger">
            Needs attention · {blocked.length} blocked
          </p>
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            {ORDER.map((cat) =>
              groups[cat].length ? (
                <span key={cat} className={toneCls(cat)}>
                  {groups[cat].length} {labelFor(cat)}
                </span>
              ) : null,
            )}
          </div>
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="btn-ghost shrink-0"
          aria-expanded={open}
        >
          {open ? "Hide" : "Review"}
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-2">
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
