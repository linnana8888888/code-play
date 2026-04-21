import { useEffect, useState, useCallback } from "react";
import type { HumanGate, Project } from "../../types/api";
import {
  getGates,
  approveGate,
  reviseGate,
  gamePreviewUrl,
  getAssetPreviews,
  getProject,
  advancePipeline,
  type AssetPreview,
  type IdeaPayload,
} from "../../api/client";
import { useWebSocket } from "../../api/websocket";
import SpecDiffGrid from "./SpecDiffGrid";
import BudgetGatePanel from "./BudgetGatePanel";

interface Props {
  projectId: string;
  initialExpandedId?: string;
}

function extractHexCodes(text: string): string[] {
  const matches = text.match(/#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g);
  if (!matches) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of matches) {
    const norm = m.toLowerCase();
    if (seen.has(norm)) continue;
    seen.add(norm);
    out.push(m);
    if (out.length >= 20) break;
  }
  return out;
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

type LastDecision = {
  task_id: string;
  kind: "approved" | "revised";
  message: string;
  at: number;
};

export default function GatesPanel({ projectId, initialExpandedId }: Props) {
  const [gates, setGates] = useState<HumanGate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [assetPreviews, setAssetPreviews] = useState<AssetPreview[]>([]);
  const [expanded, setExpanded] = useState<string | null>(initialExpandedId ?? null);
  const [playOpen, setPlayOpen] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [iterating, setIterating] = useState(false);
  const [lastDecision, setLastDecision] = useState<LastDecision | null>(null);
  const [confirming, setConfirming] = useState<{ id: string; action: "approve" | "revise" } | null>(null);

  async function refresh() {
    try {
      const [g, a, p] = await Promise.all([
        getGates(projectId),
        getAssetPreviews(projectId).catch(() => [] as AssetPreview[]),
        getProject(projectId).catch(() => null as Project | null),
      ]);
      setGates(g);
      setAssetPreviews(a);
      setProject(p);
    } catch (e) {
      console.error("getGates failed", e);
    } finally {
      setLoading(false);
    }
  }

  async function onIterate() {
    if (!project) return;
    setIterating(true);
    try {
      await advancePipeline(projectId, "iterate_artifact");
      await refresh();
    } catch (e) {
      console.error("iterate_artifact launch failed", e);
      alert(`Failed to launch iterate_artifact: ${e instanceof Error ? e.message : e}`);
    } finally {
      setIterating(false);
    }
  }

  const wsRefresh = useCallback(() => {
    refresh();
  }, [projectId]);

  useWebSocket((event) => {
    const e = event as { type?: string; data?: Record<string, unknown> };
    if (!e.data) return;
    if (e.data.project_id && e.data.project_id !== projectId) return;
    const relevant = [
      "gate_ready", "task_completed", "task_created", "task_updated",
      "pipeline_started", "roster_proposed", "agent_spawned",
    ];
    if (relevant.includes(e.type || "")) wsRefresh();
  });

  useEffect(() => {
    refresh();
  }, [projectId]);

  useEffect(() => {
    if (initialExpandedId) setExpanded(initialExpandedId);
  }, [initialExpandedId]);

  async function onApprove(
    gate: HumanGate,
    bundle?: { selected: IdeaPayload[]; custom: IdeaPayload[] },
  ) {
    setBusy(gate.task_id);
    try {
      const res = await approveGate(gate.task_id, feedback[gate.task_id] ?? "", bundle);
      const winner = res?.pick_winner ? ` — promoted ${res.pick_winner}` : "";
      const picked = bundle
        ? ` — ${bundle.selected.length + bundle.custom.length} ideas handed off`
        : "";
      setLastDecision({
        task_id: gate.task_id,
        kind: "approved",
        message: `Approved ${gate.review_of ?? gate.step_id}${winner}${picked}. Pipeline advanced.`,
        at: Date.now(),
      });
      setConfirming(null);
      await refresh();
    } catch (e) {
      setLastDecision({
        task_id: gate.task_id,
        kind: "approved",
        message: `Approval failed: ${e instanceof Error ? e.message : String(e)}`,
        at: Date.now(),
      });
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
      setLastDecision({
        task_id: gate.task_id,
        kind: "revised",
        message: `Revision sent to ${gate.review_of_agent ?? gate.review_of ?? "previous step"}. Gate stays open until they respond.`,
        at: Date.now(),
      });
      setFeedback((f) => ({ ...f, [gate.task_id]: "" }));
      setConfirming(null);
      await refresh();
    } catch (e) {
      setLastDecision({
        task_id: gate.task_id,
        kind: "revised",
        message: `Revise failed: ${e instanceof Error ? e.message : String(e)}`,
        at: Date.now(),
      });
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!lastDecision) return;
    const t = setTimeout(() => setLastDecision(null), 8000);
    return () => clearTimeout(t);
  }, [lastDecision]);

  const iterateHeader = null;

  const decisionBanner = lastDecision ? (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-start justify-between gap-3 rounded-xl border px-4 py-3 ${
        lastDecision.message.startsWith("Approval failed") ||
        lastDecision.message.startsWith("Revise failed")
          ? "border-danger/40 bg-danger/10 text-danger"
          : "border-success/40 bg-success/10 text-success"
      }`}
    >
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide">
          {lastDecision.kind === "approved" ? "Decision sent" : "Revision sent"}
        </p>
        <p className="mt-0.5 text-sm">{lastDecision.message}</p>
      </div>
      <button
        onClick={() => setLastDecision(null)}
        className="shrink-0 rounded px-2 py-0.5 text-xs opacity-70 hover:bg-black/10 hover:opacity-100"
      >
        dismiss
      </button>
    </div>
  ) : null;

  if (loading) return <p className="text-sm text-text-muted">Loading gates...</p>;
  if (gates.length === 0) {
    return (
      <div className="space-y-4">
        {iterateHeader}
        {decisionBanner}
        <p className="text-sm text-text-muted">
          {lastDecision ? "Gate closed — waiting for the pipeline to surface the next one." : "No pending human gates. Launch the Phased Producer pipeline from the Dashboard to see them here."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {iterateHeader}
      {decisionBanner}
      {gates.map((gate) => {
        const summary = summariseResult(gate.preceding_result);
        const hexCodes = extractHexCodes(summary);
        const isExpanded = expanded === gate.task_id;
        const isPlayable =
          gate.ready &&
          (gate.review_of === "build" ||
            gate.review_of === "qa-playtest" ||
            gate.step_id?.startsWith("gate-build"));
        const isLafLike =
          gate.review_of === "look-and-feel" || gate.review_of === "style-research";
        const showPlayInline = playOpen === gate.task_id;
        const isSynthesisGate =
          gate.step_id === "synthesis_gate" ||
          (gate.review_of?.startsWith("propose-") ?? false);
        const isBudgetGate =
          gate.step_id === "budget_gate" ||
          gate.review_of === "estimate-implement";

        if (isBudgetGate) {
          return (
            <div
              key={gate.task_id}
              className={`rounded-xl border p-4 ${
                gate.ready ? "border-accent/50 bg-bg-card" : "border-border bg-bg-card opacity-70"
              } ${isExpanded ? "ring-2 ring-accent" : ""}`}
            >
              <BudgetGatePanel
                projectId={projectId}
                gate={gate}
                onDecided={(msg) => {
                  setLastDecision({
                    task_id: gate.task_id,
                    kind: "approved",
                    message: msg,
                    at: Date.now(),
                  });
                  refresh();
                }}
              />
            </div>
          );
        }

        if (isSynthesisGate) {
          return (
            <div
              key={gate.task_id}
              className={`rounded-2xl border p-5 ${
                gate.ready ? "border-accent bg-bg-card" : "border-border bg-bg-card opacity-70"
              } ${isExpanded ? "ring-1 ring-accent" : ""}`}
              style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
            >
              <SpecDiffGrid
                projectId={projectId}
                gate={gate}
                busy={busy === gate.task_id}
                feedback={feedback[gate.task_id] ?? ""}
                onFeedbackChange={(v) =>
                  setFeedback((f) => ({ ...f, [gate.task_id]: v }))
                }
                confirming={
                  confirming?.id === gate.task_id ? confirming.action : null
                }
                onArmApprove={() =>
                  setConfirming({ id: gate.task_id, action: "approve" })
                }
                onArmRevise={() =>
                  setConfirming({ id: gate.task_id, action: "revise" })
                }
                onCancelConfirm={() => setConfirming(null)}
                onApprove={(bundle) => onApprove(gate, bundle)}
                onRevise={() => onRevise(gate)}
              />
            </div>
          );
        }

        return (
          <div
            key={gate.task_id}
            className={`rounded-2xl border p-5 ${
              gate.ready ? "border-accent bg-bg-card" : "border-border bg-bg-card opacity-70"
            } ${isExpanded ? "ring-1 ring-accent" : ""}`}
            style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
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
              <div className="flex flex-col items-end gap-1">
                <span className={`badge ${gate.ready ? "badge-running" : "badge-pending"}`}>
                  {gate.ready ? "ready" : "waiting"}
                </span>
                {gate.upstream_blocked ? (
                  <span
                    className="rounded-full border border-danger/40 bg-danger/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-danger"
                    title={
                      gate.upstream_blocked_ids?.length
                        ? `Blocked upstream: ${gate.upstream_blocked_ids.join(", ")}`
                        : "An upstream task is blocked"
                    }
                  >
                    upstream blocked
                  </span>
                ) : null}
              </div>
            </div>
            {gate.upstream_blocked && gate.upstream_blocked_ids?.length ? (
              <p className="mt-2 text-[11px] text-danger">
                Blocked upstream tasks:{" "}
                <span style={{ fontFamily: "var(--font-mono)" }}>
                  {gate.upstream_blocked_ids.join(", ")}
                </span>{" "}
                — resolve them from the Needs Attention banner to let this gate proceed.
              </p>
            ) : null}

            {summary ? (
              <pre className="mt-3 max-h-64 overflow-auto rounded bg-bg p-2 text-xs leading-relaxed text-text-muted whitespace-pre-wrap">
                {summary}
              </pre>
            ) : (
              <p className="mt-3 text-xs italic text-text-muted">
                No artifact yet — the preceding step hasn't posted a result.
              </p>
            )}

            {hexCodes.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {hexCodes.map((h) => (
                  <span
                    key={h}
                    className="flex items-center gap-1.5 rounded-full border border-border bg-bg px-2 py-0.5 text-[11px] text-text-muted"
                  >
                    <span
                      className="inline-block h-3 w-3 rounded-full border border-black/20"
                      style={{ background: h }}
                    />
                    {h}
                  </span>
                ))}
              </div>
            ) : null}

            {isLafLike && assetPreviews.length > 0 ? (
              <div className="mt-3">
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  Referenced assets ({assetPreviews.length})
                </p>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
                  {assetPreviews.slice(0, 12).map((a) => (
                    <a
                      key={a.path}
                      href={a.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group block overflow-hidden rounded border border-border bg-bg"
                      title={a.path}
                    >
                      <img
                        src={a.url}
                        alt={a.path}
                        className="h-16 w-full object-cover transition-transform group-hover:scale-105"
                        loading="lazy"
                      />
                      <p className="truncate px-1 py-0.5 text-[10px] text-text-muted">{a.path}</p>
                    </a>
                  ))}
                </div>
              </div>
            ) : null}

            {isPlayable ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <a
                  href={gamePreviewUrl(projectId)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-accent"
                >
                  ▶ Play build (new tab)
                </a>
                <button
                  onClick={() => setPlayOpen(showPlayInline ? null : gate.task_id)}
                  className="btn-ghost"
                >
                  {showPlayInline ? "Hide inline preview" : "Play inline"}
                </button>
              </div>
            ) : null}

            {showPlayInline ? (
              <iframe
                key={`${gate.task_id}-iframe`}
                src={gamePreviewUrl(projectId)}
                sandbox="allow-scripts allow-same-origin"
                className="mt-3 h-96 w-full rounded-2xl border border-border bg-black"
                title="Game preview"
              />
            ) : null}

            <textarea
              rows={2}
              value={feedback[gate.task_id] ?? ""}
              onChange={(e) =>
                setFeedback((f) => ({ ...f, [gate.task_id]: e.target.value }))
              }
              placeholder="Optional notes on approval, or required changes for revise..."
              className="mt-3 w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm text-text outline-none focus:border-accent"
            />

            <GateDecisionRow
              gate={gate}
              busy={busy === gate.task_id}
              feedback={feedback[gate.task_id] ?? ""}
              confirming={
                confirming?.id === gate.task_id ? confirming.action : null
              }
              onArmApprove={() =>
                setConfirming({ id: gate.task_id, action: "approve" })
              }
              onArmRevise={() =>
                setConfirming({ id: gate.task_id, action: "revise" })
              }
              onCancelConfirm={() => setConfirming(null)}
              onApprove={() => onApprove(gate)}
              onRevise={() => onRevise(gate)}
            />
          </div>
        );
      })}
    </div>
  );
}

function GateDecisionRow({
  gate,
  busy,
  feedback,
  confirming,
  onArmApprove,
  onArmRevise,
  onCancelConfirm,
  onApprove,
  onRevise,
}: {
  gate: HumanGate;
  busy: boolean;
  feedback: string;
  confirming: "approve" | "revise" | null;
  onArmApprove: () => void;
  onArmRevise: () => void;
  onCancelConfirm: () => void;
  onApprove: () => void;
  onRevise: () => void;
}) {
  const reviseDisabled = !gate.ready || busy || !feedback.trim();
  const approveDisabled = !gate.ready || busy;
  const hint = !gate.ready
    ? gate.upstream_blocked
      ? "Upstream task is blocked — retry it from Needs Attention to unblock this gate."
      : "Waiting on upstream step to complete — buttons enable automatically."
    : !feedback.trim()
      ? "Request changes requires a note. Approve works without one."
      : null;

  if (confirming === "approve") {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-success/40 bg-success/10 px-3 py-2">
        <span className="text-xs text-success">
          Confirm: approve this gate and advance the pipeline?
        </span>
        <button
          onClick={onApprove}
          disabled={busy}
          className="rounded-lg bg-success px-3 py-1 text-xs font-semibold text-bg hover:bg-success/90 disabled:opacity-50"
        >
          {busy ? "Sending…" : "✓ Confirm approve"}
        </button>
        <button
          onClick={onCancelConfirm}
          disabled={busy}
          className="rounded-lg bg-bg-hover px-3 py-1 text-xs font-medium text-text-muted hover:text-text"
        >
          Cancel
        </button>
      </div>
    );
  }
  if (confirming === "revise") {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2">
        <span className="text-xs text-warning">
          Confirm: send feedback back to {gate.review_of_agent ?? "the previous step"}?
        </span>
        <button
          onClick={onRevise}
          disabled={busy || !feedback.trim()}
          className="rounded-lg bg-warning px-3 py-1 text-xs font-semibold text-bg hover:bg-warning/90 disabled:opacity-50"
        >
          {busy ? "Sending…" : "✓ Confirm revise"}
        </button>
        <button
          onClick={onCancelConfirm}
          disabled={busy}
          className="rounded-lg bg-bg-hover px-3 py-1 text-xs font-medium text-text-muted hover:text-text"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <button
        disabled={approveDisabled}
        onClick={onArmApprove}
        className="rounded-lg bg-success/20 px-3 py-1.5 text-xs font-medium text-success hover:bg-success/30 disabled:opacity-50"
      >
        Approve…
      </button>
      <button
        disabled={reviseDisabled}
        onClick={onArmRevise}
        className="rounded-lg bg-warning/20 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/30 disabled:opacity-50"
      >
        Request changes…
      </button>
      {hint && <span className="text-[10px] italic text-text-muted">{hint}</span>}
    </div>
  );
}
