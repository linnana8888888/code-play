/**
 * BlockedTaskActions — renders the right action on a blocked task card
 * based on `result.failure_category`:
 *
 *   budget_exhausted → numeric input pre-filled with suggested_cap +
 *                      "Lift cap & retry" button (calls retryTask with
 *                      budget_max_tokens_override).
 *   transient        → plain "Retry" button (provider 5xx / 429 / timeout).
 *   spawn            → "Retry" button + hint about agent registry drift.
 *   permanent        → "Force retry" (after you fix config) + the stall
 *                      reason/hint rendered prominently so the human
 *                      knows what to fix.
 *
 * All paths route through POST /api/tasks/:id/retry.
 */
import { useState } from "react";
import type { Task, FailureCategory } from "../../types/api";
import { retryTask, cancelTask } from "../../api/client";

interface Props {
  task: Task;
  onRetried?: () => void;
  compact?: boolean;
}

function fmtTokens(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

function categoryOf(task: Task): FailureCategory {
  const raw = (task.result?.failure_category ?? "permanent") as FailureCategory;
  return raw;
}

function labelFor(cat: FailureCategory): string {
  switch (cat) {
    case "budget_exhausted":
      return "Budget exhausted";
    case "transient":
      return "Transient provider error";
    case "spawn":
      return "Agent spawn failed";
    default:
      return "Blocked";
  }
}

function toneFor(cat: FailureCategory): string {
  if (cat === "budget_exhausted") return "warning";
  if (cat === "transient") return "info";
  if (cat === "spawn") return "warning";
  return "danger";
}

export default function BlockedTaskActions({ task, onRetried, compact }: Props) {
  const cat = categoryOf(task);
  const tone = toneFor(cat);
  const result = task.result ?? {};

  const suggested =
    typeof result.suggested_cap === "number" && result.suggested_cap > 0
      ? result.suggested_cap
      : 400000;

  const [newCap, setNewCap] = useState<number>(suggested);
  const [busy, setBusy] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function doDismiss() {
    setDismissing(true);
    setErr(null);
    try {
      await cancelTask(task.id);
      onRetried?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDismissing(false);
    }
  }

  async function doRetry(cap?: number) {
    setBusy(true);
    setErr(null);
    try {
      await retryTask(task.id, cap ? { budget_max_tokens_override: cap } : {});
      onRetried?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const errText =
    result.error ||
    result.stall_reason ||
    (result.spawn_errors && result.spawn_errors.length
      ? result.spawn_errors[result.spawn_errors.length - 1]
      : undefined);

  const toneCls =
    tone === "warning"
      ? "border-warning/40 bg-warning/10"
      : tone === "info"
        ? "border-info/40 bg-info/10"
        : "border-danger/40 bg-danger/10";
  const labelCls =
    tone === "warning"
      ? "text-warning"
      : tone === "info"
        ? "text-info"
        : "text-danger";

  return (
    <div className={`rounded-lg border ${toneCls} ${compact ? "p-2" : "p-3"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={`text-[11px] font-semibold uppercase tracking-wide ${labelCls}`}>
            {labelFor(cat)}
          </p>
          {errText ? (
            <p
              className="mt-0.5 text-[11px] text-text-muted"
              title={String(errText)}
              style={{ overflowWrap: "anywhere" }}
            >
              {String(errText).slice(0, 160)}
            </p>
          ) : null}
          {result.stall_hint ? (
            <p className="mt-0.5 text-[11px] italic text-text-muted">
              Hint: {String(result.stall_hint)}
            </p>
          ) : null}
        </div>
      </div>

      {cat === "budget_exhausted" ? (
        <div className="mt-2 space-y-1">
          <p className="text-[11px] text-text-muted">
            Used {fmtTokens(result.tokens_used)} / {fmtTokens(result.prev_cap)}. Lift cap to:
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              type="number"
              value={newCap}
              onChange={(e) => setNewCap(Number(e.target.value))}
              step={50000}
              min={(result.prev_cap ?? 0) + 50000}
              className="w-24 rounded border border-border bg-white px-1.5 py-0.5 text-[11px] font-mono"
              disabled={busy}
            />
            <button
              onClick={() => doRetry(newCap)}
              disabled={busy || !Number.isFinite(newCap) || newCap <= (result.prev_cap ?? 0)}
              className="rounded-lg bg-warning px-2 py-0.5 text-[11px] font-semibold text-bg hover:bg-warning/90 disabled:opacity-50"
            >
              {busy ? "Lifting…" : `Lift & retry (${fmtTokens(newCap)})`}
            </button>
            <button
              onClick={doDismiss}
              disabled={dismissing}
              className="rounded-lg border border-border px-2 py-0.5 text-[11px] text-text-muted hover:bg-bg-hover disabled:opacity-50"
            >
              {dismissing ? "Dismissing…" : "Dismiss"}
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex items-center gap-1.5">
          <button
            onClick={() => doRetry()}
            disabled={busy}
            className={`rounded-lg px-2 py-0.5 text-[11px] font-semibold text-bg disabled:opacity-50 ${
              tone === "danger"
                ? "bg-danger hover:bg-danger/90"
                : tone === "warning"
                  ? "bg-warning hover:bg-warning/90"
                  : "bg-info hover:bg-info/90"
            }`}
          >
            {busy
              ? "Retrying…"
              : cat === "permanent"
                ? "Force retry"
                : "Retry"}
          </button>
          <button
            onClick={doDismiss}
            disabled={dismissing}
            className="rounded-lg border border-border px-2 py-0.5 text-[11px] text-text-muted hover:bg-bg-hover disabled:opacity-50"
          >
            {dismissing ? "Dismissing…" : "Dismiss"}
          </button>
        </div>
      )}

      {err ? <p className="mt-1 text-[11px] text-danger">Error: {err}</p> : null}
    </div>
  );
}
