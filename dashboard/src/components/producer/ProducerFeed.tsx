import { useState, useEffect, useRef } from "react";
import { getProducerStatus, getProducerNotes } from "../../api/client";
import { useWebSocket } from "../../api/websocket";

/* ── Types ── */
interface ProducerNote {
  id?: string;
  timestamp: string;
  text: string;
  severity?: "info" | "warning" | "error";
}

interface BlockedStep {
  step: string;
  reason?: string;
}

interface Intervention {
  id?: string;
  timestamp?: string;
  action: string;
  detail?: string;
}

interface RunStatus {
  status: "running" | "blocked" | "waiting_human" | "completed" | "idle" | string;
  phase?: string;
  steps_done?: number;
  steps_total?: number;
  current_steps?: string[];
  blocked_steps?: BlockedStep[] | string[];
  budget_used_pct?: number;
  last_event?: string;
  producer_notes?: ProducerNote[];
  interventions?: Intervention[];
}

interface ProducerStatusData {
  status: string;
  phase?: string;
  steps_done?: number;
  steps_total?: number;
  current_steps?: string[];
  blocked_steps?: BlockedStep[] | string[];
  budget_used_pct?: number;
  last_event?: string;
  note?: string;
  severity?: "info" | "warning" | "error";
  run_status?: RunStatus | null;
}

/* ── Helpers ── */
function relativeTime(ts: string): string {
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function pct(done?: number, total?: number): number {
  if (!total || total === 0) return 0;
  return Math.min(100, Math.round(((done ?? 0) / total) * 100));
}

function normalizeBlockedSteps(steps?: BlockedStep[] | string[]): BlockedStep[] {
  if (!steps || steps.length === 0) return [];
  return steps.map((s) =>
    typeof s === "string" ? { step: s } : s,
  );
}

/* ── Status badge ── */
function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    running: { label: "running", cls: "badge badge-running" },
    blocked: { label: "blocked", cls: "badge badge-failed" },
    waiting_human: { label: "waiting", cls: "badge badge-assigned" },
    completed: { label: "done", cls: "badge" },
    idle: { label: "idle", cls: "badge" },
  };
  const entry = map[status] ?? { label: status, cls: "badge" };
  return (
    <span className={entry.cls} style={status === "running" ? { animation: "pulse 2s infinite" } : {}}>
      {entry.label}
    </span>
  );
}

/* ── Progress bar ── */
function ProgressBar({ value, thin, color }: { value: number; thin?: boolean; color?: string }) {
  const h = thin ? "3px" : "6px";
  const bg = color ?? "var(--color-accent)";
  return (
    <div
      style={{
        height: h,
        background: "var(--color-border)",
        borderRadius: "999px",
        overflow: "hidden",
        flex: 1,
        minWidth: 60,
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${value}%`,
          background: bg,
          borderRadius: "999px",
          transition: "width 0.4s ease",
        }}
      />
    </div>
  );
}

/* ── Note row ── */
function NoteRow({ note, isLatest }: { note: ProducerNote; isLatest: boolean }) {
  const borderColor =
    note.severity === "error"
      ? "var(--color-danger)"
      : note.severity === "warning"
      ? "var(--color-warning)"
      : "transparent";

  return (
    <div
      className="note-row"
      style={{
        borderLeft: `3px solid ${borderColor}`,
        paddingLeft: note.severity && note.severity !== "info" ? 8 : 4,
        paddingTop: 5,
        paddingBottom: 5,
        background: isLatest ? "var(--color-accent-tint)" : "transparent",
        borderRadius: isLatest ? 6 : 0,
        transition: "background 0.3s ease",
        animation: isLatest ? "fadeIn 0.3s ease" : undefined,
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--color-text-muted)",
          marginRight: 8,
          whiteSpace: "nowrap",
        }}
      >
        {relativeTime(note.timestamp)}
      </span>
      <span style={{ fontSize: 12, color: "var(--color-text)" }}>{note.text}</span>
    </div>
  );
}

/* ── Main component ── */
export default function ProducerFeed({ projectId }: { projectId: string }) {
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [liveData, setLiveData] = useState<ProducerStatusData | null>(null);
  const [notes, setNotes] = useState<ProducerNote[]>([]);
  const [interventionsOpen, setInterventionsOpen] = useState(false);
  const notesRef = useRef<HTMLDivElement>(null);

  // Initial fetch
  useEffect(() => {
    getProducerStatus(projectId).then((data) => {
      if (data) setRunStatus(data as RunStatus);
    });
    getProducerNotes(projectId).then((data) => {
      if (Array.isArray(data)) setNotes(data as ProducerNote[]);
    });
  }, [projectId]);

  // Sync notes from run_status when it updates
  useEffect(() => {
    if (runStatus?.producer_notes && runStatus.producer_notes.length > 0) {
      setNotes(runStatus.producer_notes);
    }
  }, [runStatus]);

  // WebSocket subscription
  useWebSocket((event) => {
    if (event.type !== "producer_status") return;
    const d = event.data as unknown as { project_id?: string } & ProducerStatusData;
    if (d.project_id && d.project_id !== projectId) return;

    setLiveData(d);

    // Merge run_status if present
    if (d.run_status !== undefined) {
      setRunStatus(d.run_status);
    } else {
      // Patch top-level fields into runStatus
      setRunStatus((prev) => {
        if (!prev && !d.status) return prev;
        const base: RunStatus = prev ?? { status: d.status };
        return {
          ...base,
          status: d.status ?? base.status,
          phase: d.phase ?? base.phase,
          steps_done: d.steps_done ?? base.steps_done,
          steps_total: d.steps_total ?? base.steps_total,
          current_steps: d.current_steps ?? base.current_steps,
          blocked_steps: d.blocked_steps ?? base.blocked_steps,
          budget_used_pct: d.budget_used_pct ?? base.budget_used_pct,
          last_event: d.last_event ?? base.last_event,
        };
      });
    }

    // Append new note from event
    if (d.note) {
      const newNote: ProducerNote = {
        id: `live-${Date.now()}`,
        timestamp: event.timestamp ?? new Date().toISOString(),
        text: d.note,
        severity: d.severity ?? "info",
      };
      setNotes((prev) => [newNote, ...prev].slice(0, 100));
    }
  });

  // Derive display values — prefer live data, fall back to run_status
  const status = liveData?.status ?? runStatus?.status ?? "idle";
  const phase = liveData?.phase ?? runStatus?.phase;
  const stepsDone = liveData?.steps_done ?? runStatus?.steps_done ?? 0;
  const stepsTotal = liveData?.steps_total ?? runStatus?.steps_total ?? 0;
  const currentSteps = liveData?.current_steps ?? runStatus?.current_steps ?? [];
  const blockedSteps = normalizeBlockedSteps(liveData?.blocked_steps ?? runStatus?.blocked_steps);
  const budgetPct = liveData?.budget_used_pct ?? runStatus?.budget_used_pct ?? 0;
  const lastEvent = liveData?.last_event ?? runStatus?.last_event;
  const interventions = runStatus?.interventions ?? [];
  const progress = pct(stepsDone, stepsTotal);

  const isNoRun = !runStatus && !liveData;

  return (
    <>
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.6; }
        }
      `}</style>

      <div
        className="rounded-2xl border border-border bg-bg-card overflow-hidden"
        style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
      >
        {/* Header row */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3.5">
          <span className="text-[15px] font-semibold tight-heading">🎬 Producer</span>
          <StatusBadge status={status} />
          <div className="ml-auto flex items-center gap-3 min-w-0">
            {phase && (
              <span
                className="text-xs text-text-muted"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {phase} phase
              </span>
            )}
            {stepsTotal > 0 && (
              <>
                <ProgressBar value={progress} />
                <span className="text-xs text-text-muted whitespace-nowrap">
                  {stepsDone}/{stepsTotal}
                </span>
              </>
            )}
          </div>
        </div>

        {isNoRun ? (
          <div className="px-5 py-8 text-sm text-text-muted text-center">
            No active run
          </div>
        ) : (
          <div className="px-5 py-4 space-y-4">
            {/* Current activity */}
            {status === "running" && currentSteps.length > 0 && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-medium text-text-muted">Now:</span>
                  {currentSteps.map((s) => (
                    <span key={s} className="badge badge-running" style={{ fontSize: 11 }}>
                      {s}
                    </span>
                  ))}
                </div>
                {budgetPct > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-text-muted whitespace-nowrap">
                      Budget {budgetPct}%
                    </span>
                    <ProgressBar
                      value={budgetPct}
                      thin
                      color={
                        budgetPct > 80
                          ? "var(--color-danger)"
                          : budgetPct > 60
                          ? "var(--color-warning)"
                          : "var(--color-accent)"
                      }
                    />
                  </div>
                )}
              </div>
            )}

            {/* Last event */}
            {lastEvent && (
              <p
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--color-text-muted)",
                  overflowWrap: "anywhere",
                }}
              >
                {lastEvent}
              </p>
            )}

            {/* Blocked steps banner */}
            {blockedSteps.length > 0 && (
              <div className="space-y-1">
                {blockedSteps.map((b, i) => (
                  <div
                    key={i}
                    className="rounded-xl px-4 py-2 text-sm"
                    style={{
                      background: "#fee2e2",
                      borderLeft: "4px solid var(--color-danger)",
                      color: "#991b1b",
                    }}
                  >
                    ⚠ Blocked: <strong>{b.step}</strong>
                    {b.reason ? ` — ${b.reason}` : ""}
                  </div>
                ))}
              </div>
            )}

            {/* Producer notes feed */}
            <div>
              <p className="mono-label mb-1.5">Notes</p>
              <div
                ref={notesRef}
                style={{ maxHeight: 300, overflowY: "auto" }}
                className="space-y-0.5"
              >
                {notes.length === 0 ? (
                  <p className="text-xs text-text-muted py-2">No notes yet.</p>
                ) : (
                  notes.map((n, i) => (
                    <NoteRow
                      key={n.id ?? `${n.timestamp}-${i}`}
                      note={n}
                      isLatest={i === 0}
                    />
                  ))
                )}
              </div>
            </div>

            {/* Interventions (collapsible) */}
            {interventions.length > 0 && (
              <div>
                <button
                  onClick={() => setInterventionsOpen((v) => !v)}
                  className="btn-ghost"
                  style={{ padding: "2px 10px", fontSize: 12 }}
                >
                  {interventionsOpen ? "▾" : "▸"} Interventions ({interventions.length})
                </button>
                {interventionsOpen && (
                  <div className="mt-2 space-y-1">
                    {interventions.map((iv, i) => (
                      <div
                        key={iv.id ?? i}
                        className="rounded-lg border border-border px-3 py-2 text-xs text-text-muted"
                      >
                        {iv.timestamp && (
                          <span
                            style={{ fontFamily: "var(--font-mono)", marginRight: 8 }}
                          >
                            {relativeTime(iv.timestamp)}
                          </span>
                        )}
                        <strong>{iv.action}</strong>
                        {iv.detail ? ` — ${iv.detail}` : ""}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
