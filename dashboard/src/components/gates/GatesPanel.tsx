import { useEffect, useState } from "react";
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
} from "../../api/client";
import SpecDiffGrid from "./SpecDiffGrid";

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

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [projectId]);

  useEffect(() => {
    if (initialExpandedId) setExpanded(initialExpandedId);
  }, [initialExpandedId]);

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

  const iterateEnabled = Boolean(project?.iterate_enabled);
  const iterateHeader = iterateEnabled ? (
    <div
      className="flex items-center justify-between rounded-2xl border p-4"
      style={{ borderColor: "var(--color-accent)", background: "var(--color-accent-tint)" }}
    >
      <div>
        <p className="mono-label" style={{ color: "var(--color-accent-hover)" }}>
          Iterate on this artifact
        </p>
        <p className="mt-1 text-xs text-text-muted">
          Run the iterate_artifact pipeline: playtest → postmortem → propose ×4
          → synthesis gate → implement. Loops up to the cycle budget (default 5).
        </p>
      </div>
      <button onClick={onIterate} disabled={iterating} className="btn-accent">
        {iterating ? "Launching…" : "▶ Iterate"}
      </button>
    </div>
  ) : null;

  if (loading) return <p className="text-sm text-text-muted">Loading gates...</p>;
  if (gates.length === 0) {
    return (
      <div className="space-y-4">
        {iterateHeader}
        <p className="text-sm text-text-muted">
          No pending human gates. Launch the Phased Producer pipeline from the Dashboard to see them here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {iterateHeader}
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
                onApprove={() => onApprove(gate)}
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
              <span className={`badge ${gate.ready ? "badge-running" : "badge-pending"}`}>
                {gate.ready ? "ready" : "waiting"}
              </span>
            </div>

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

            <div className="mt-3 flex gap-2">
              <button
                disabled={!gate.ready || busy === gate.task_id}
                onClick={() => onApprove(gate)}
                className="btn-primary"
              >
                {busy === gate.task_id ? "…" : "Approve"}
              </button>
              <button
                disabled={!gate.ready || busy === gate.task_id || !(feedback[gate.task_id] ?? "").trim()}
                onClick={() => onRevise(gate)}
                className="btn-ghost"
              >
                {busy === gate.task_id ? "…" : "Request changes"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
