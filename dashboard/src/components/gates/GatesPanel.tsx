import { useEffect, useState } from "react";
import type { HumanGate } from "../../types/api";
import { getGates, approveGate, reviseGate } from "../../api/client";

interface Props {
  projectId: string;
}

function summariseResult(r: Record<string, unknown> | null): string {
  if (!r) return "";
  if (typeof r.summary === "string") return r.summary;
  try {
    return JSON.stringify(r, null, 2);
  } catch {
    return String(r);
  }
}

export default function GatesPanel({ projectId }: Props) {
  const [gates, setGates] = useState<HumanGate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, string>>({});

  async function refresh() {
    try {
      setGates(await getGates(projectId));
    } catch (e) {
      console.error("getGates failed", e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [projectId]);

  async function onApprove(gate: HumanGate) {
    setBusy(gate.task_id);
    try {
      await approveGate(gate.task_id, feedback[gate.task_id] ?? "");
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function onRevise(gate: HumanGate) {
    const note = (feedback[gate.task_id] ?? "").trim();
    if (!note) {
      alert("Feedback required to request changes.");
      return;
    }
    setBusy(gate.task_id);
    try {
      await reviseGate(gate.task_id, note);
      setFeedback((f) => ({ ...f, [gate.task_id]: "" }));
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Loading gates...</p>;
  if (gates.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        No pending human gates. Launch the Phased Producer pipeline from the Dashboard to see them here.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {gates.map((gate) => {
        const summary = summariseResult(gate.preceding_result);
        return (
          <div
            key={gate.task_id}
            className={`rounded-xl border p-4 ${
              gate.ready ? "border-accent/50 bg-bg-card" : "border-border bg-bg-card opacity-70"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs text-text-muted">
                  {gate.pipeline_label} · step {gate.step_id}
                </p>
                <h3 className="text-base font-semibold">
                  Review {gate.review_of}
                  {gate.review_of_agent ? (
                    <span className="ml-2 rounded bg-bg-hover px-1.5 py-0.5 text-[10px] font-normal text-text-muted">
                      by {gate.review_of_agent}
                    </span>
                  ) : null}
                </h3>
                <p className="mt-1 text-xs text-text-muted">{gate.prompt}</p>
              </div>
              <span
                className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                  gate.ready ? "bg-success/20 text-success" : "bg-warning/20 text-warning"
                }`}
              >
                {gate.ready ? "ready for review" : "waiting on upstream"}
              </span>
            </div>

            {summary ? (
              <pre className="mt-3 max-h-48 overflow-auto rounded bg-bg p-2 text-xs leading-relaxed text-text-muted">
                {summary}
              </pre>
            ) : (
              <p className="mt-3 text-xs italic text-text-muted">
                No artifact yet — the preceding step hasn't posted a result.
              </p>
            )}

            <textarea
              rows={2}
              value={feedback[gate.task_id] ?? ""}
              onChange={(e) =>
                setFeedback((f) => ({ ...f, [gate.task_id]: e.target.value }))
              }
              placeholder="Optional notes on approval, or required changes for revise..."
              className="mt-3 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />

            <div className="mt-3 flex gap-2">
              <button
                disabled={!gate.ready || busy === gate.task_id}
                onClick={() => onApprove(gate)}
                className="rounded-lg bg-success/20 px-3 py-1.5 text-xs font-medium text-success hover:bg-success/30 disabled:opacity-50"
              >
                {busy === gate.task_id ? "..." : "Approve"}
              </button>
              <button
                disabled={!gate.ready || busy === gate.task_id || !(feedback[gate.task_id] ?? "").trim()}
                onClick={() => onRevise(gate)}
                className="rounded-lg bg-warning/20 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/30 disabled:opacity-50"
              >
                {busy === gate.task_id ? "..." : "Request changes"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
