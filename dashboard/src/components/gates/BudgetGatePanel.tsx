/*
 * BudgetGatePanel — renders the budget_gate in iterate_artifact.
 *
 * Reads `implementation_plan_{iteration_tag}` from project memory. The
 * tech-lead estimator emitted a ```json fenced block with per-idea token
 * forecasts, a recommended split, and a mode recommendation. Human picks:
 *   - parallel   → N engineers in worktrees + lead merge coordinator.
 *   - extend_cap → single engineer with a bumped 200k cap.
 *   - drop_ideas → kept subset that fits inside 200k.
 * Decision is POSTed via approveBudgetGate; backend serialises it to
 * `budget_decision_{tag}` + (on parallel) fans out engineer sub-tasks.
 */
import { useEffect, useMemo, useState } from "react";
import type {
  BudgetDecisionPayload,
  BudgetMode,
  HumanGate,
  ImplementationPlan,
  ImplementationPlanSplit,
} from "../../types/api";
import { approveBudgetGate, getMemory, reviseGate } from "../../api/client";

const DEFAULT_CAP = 200000;

interface Props {
  projectId: string;
  gate: HumanGate;
  onDecided: (summary: string) => void;
}

async function readOrNull(
  projectId: string,
  key: string,
): Promise<string | null> {
  try {
    const r = await getMemory(projectId, "artifact", key);
    return r?.content ?? null;
  } catch {
    return null;
  }
}

function parsePlan(raw: string | null): ImplementationPlan | null {
  if (!raw) return null;
  const fence = raw.match(/```json\s*([\s\S]*?)```/i);
  const body = (fence?.[1] ?? raw).trim();
  try {
    return JSON.parse(body) as ImplementationPlan;
  } catch {
    return null;
  }
}

function fmtTokens(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

export default function BudgetGatePanel({ projectId, gate, onDecided }: Props) {
  const [plan, setPlan] = useState<ImplementationPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<BudgetMode>("parallel");
  const [extendedCap, setExtendedCap] = useState<number>(350000);
  const [keptIds, setKeptIds] = useState<Set<string>>(new Set());
  const [split, setSplit] = useState<ImplementationPlanSplit[]>([]);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"approve" | "revise" | null>(null);
  const tag = gate.iteration_tag ?? (gate.cycle_n ? `v${gate.cycle_n}` : "v1");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      const raw = await readOrNull(projectId, `implementation_plan_${tag}`);
      const parsed = parsePlan(raw);
      if (!alive) return;
      setPlan(parsed);
      if (parsed) {
        if (parsed.recommendation) setMode(parsed.recommendation);
        setSplit(parsed.recommended_split ? [...parsed.recommended_split] : []);
        setKeptIds(new Set((parsed.ideas ?? []).map((i) => i.id)));
      }
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [projectId, tag]);

  const totalParallel = plan?.total_tokens_parallel ?? 0;
  const totalSingle = plan?.total_tokens_single ?? 0;
  const overCap = totalSingle > DEFAULT_CAP;
  const keptTokens = useMemo(() => {
    if (!plan?.ideas) return 0;
    return plan.ideas
      .filter((i) => keptIds.has(i.id))
      .reduce((acc, i) => acc + (i.est_tokens ?? 0), 0);
  }, [plan, keptIds]);

  const toggleKept = (id: string) => {
    setKeptIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const patchSplitEntry = (idx: number, patch: Partial<ImplementationPlanSplit>) => {
    setSplit((prev) =>
      prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)),
    );
  };

  const addEngineer = () => {
    setSplit((prev) => [
      ...prev,
      {
        engineer_id: `eng-${prev.length + 1}`,
        idea_ids: [],
        est_tokens: 0,
        primary_files: [],
      },
    ]);
  };

  const removeEngineer = (idx: number) => {
    setSplit((prev) => prev.filter((_, i) => i !== idx));
  };

  const buildDecision = (): BudgetDecisionPayload | null => {
    if (mode === "parallel") {
      if (split.length === 0) {
        setError("Parallel mode requires at least one engineer in the split.");
        return null;
      }
      return { mode, split, reason: feedback };
    }
    if (mode === "extend_cap") {
      if (!Number.isFinite(extendedCap) || extendedCap <= DEFAULT_CAP) {
        setError(`extend_cap must be greater than ${DEFAULT_CAP}.`);
        return null;
      }
      return { mode, extended_cap: extendedCap, reason: feedback };
    }
    const kept = Array.from(keptIds);
    if (!kept.length) {
      setError("drop_ideas requires at least one kept idea.");
      return null;
    }
    return { mode, kept_ids: kept, reason: feedback };
  };

  const onApproveClick = async () => {
    const decision = buildDecision();
    if (!decision) return;
    setBusy(true);
    setError(null);
    try {
      await approveBudgetGate(gate.task_id, feedback, decision);
      const summary =
        decision.mode === "parallel"
          ? `Parallel fan-out: ${decision.split?.length ?? 0} engineer${(decision.split?.length ?? 0) === 1 ? "" : "s"}.`
          : decision.mode === "extend_cap"
            ? `Extended cap to ${fmtTokens(decision.extended_cap)}.`
            : `Dropped heavy ideas — ${decision.kept_ids?.length ?? 0} kept.`;
      onDecided(summary);
      setConfirming(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onReviseClick = async () => {
    const note = feedback.trim();
    if (!note) {
      setError("Feedback required to request changes.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await reviseGate(gate.task_id, note);
      onDecided("Sent back to estimator for revision.");
      setConfirming(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <p className="text-sm text-text-muted">Loading implementation plan…</p>;
  }

  if (!plan) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-warning">
          No <code>implementation_plan_{tag}</code> artifact found yet — wait
          for estimate-implement to finish, or request a revision.
        </p>
      </div>
    );
  }

  const approveLabel =
    mode === "parallel"
      ? `Approve parallel (${split.length} engineer${split.length === 1 ? "" : "s"})`
      : mode === "extend_cap"
        ? `Approve extend cap → ${fmtTokens(extendedCap)}`
        : `Approve drop → ${keptIds.size} kept`;

  return (
    <div className="space-y-4">
      <header>
        <p className="text-xs text-text-muted">
          {gate.pipeline_label} · step {gate.step_id} · cycle {gate.cycle_n ?? "?"} → {tag}
        </p>
        <h3 className="text-base font-semibold">Budget gate</h3>
        <p className="mt-1 text-xs text-text-muted">{gate.prompt}</p>
      </header>

      <section className="rounded-lg border border-border bg-bg p-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Single-engineer total" value={fmtTokens(totalSingle)} warn={overCap} />
          <Stat label="Parallel total" value={fmtTokens(totalParallel)} />
          <Stat
            label="Lead coordinator"
            value={fmtTokens(plan.lead_coordinator_tokens)}
          />
          <Stat label="Default cap" value={fmtTokens(DEFAULT_CAP)} />
        </div>
        {plan.recommendation ? (
          <p className="mt-2 text-[11px] text-text-muted">
            Estimator recommends <strong>{plan.recommendation}</strong>
            {plan.recommendation_reason ? ` — ${plan.recommendation_reason}` : ""}
          </p>
        ) : null}
      </section>

      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Per-idea forecast ({plan.ideas?.length ?? 0})
        </h4>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-bg-hover text-text-muted">
              <tr>
                <th className="px-2 py-1 text-left">Keep</th>
                <th className="px-2 py-1 text-left">Id</th>
                <th className="px-2 py-1 text-left">Title</th>
                <th className="px-2 py-1 text-left">Files</th>
                <th className="px-2 py-1 text-right">Est tokens</th>
                <th className="px-2 py-1 text-left">Complexity</th>
                <th className="px-2 py-1 text-left">Conflicts</th>
              </tr>
            </thead>
            <tbody>
              {(plan.ideas ?? []).map((idea) => (
                <tr key={idea.id} className="border-t border-border">
                  <td className="px-2 py-1">
                    <input
                      type="checkbox"
                      disabled={mode !== "drop_ideas"}
                      checked={keptIds.has(idea.id)}
                      onChange={() => toggleKept(idea.id)}
                    />
                  </td>
                  <td className="px-2 py-1 font-mono">{idea.id}</td>
                  <td className="px-2 py-1">{idea.title ?? "—"}</td>
                  <td className="px-2 py-1 truncate max-w-[14rem]">
                    {(idea.files_touched ?? []).join(", ") || "—"}
                  </td>
                  <td className="px-2 py-1 text-right">{fmtTokens(idea.est_tokens)}</td>
                  <td className="px-2 py-1">{idea.complexity ?? "—"}</td>
                  <td className="px-2 py-1">
                    {(idea.conflicts_with ?? []).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {mode === "drop_ideas" ? (
          <p className="mt-1 text-[11px] text-text-muted">
            Kept so far: <strong>{fmtTokens(keptTokens)}</strong> (goal: ≤ {fmtTokens(DEFAULT_CAP)})
          </p>
        ) : null}
      </section>

      {plan.conflicts && plan.conflicts.length > 0 ? (
        <section className="rounded-lg border border-warning/40 bg-warning/10 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-warning">
            File-level conflicts ({plan.conflicts.length})
          </h4>
          <ul className="mt-1 space-y-1 text-xs">
            {plan.conflicts.map((c, i) => (
              <li key={i}>
                <code>{c.file ?? "?"}</code>
                {c.line_region ? <span> [{c.line_region}]</span> : null} ·{" "}
                {(c.idea_ids ?? []).join(", ") || "?"}
                {c.note ? <span className="text-text-muted"> — {c.note}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Decision
        </h4>
        <div className="flex flex-wrap gap-2">
          <ModePill mode="parallel" active={mode} onClick={setMode}>
            Parallel split ({split.length})
          </ModePill>
          <ModePill mode="extend_cap" active={mode} onClick={setMode}>
            Extend cap
          </ModePill>
          <ModePill mode="drop_ideas" active={mode} onClick={setMode}>
            Drop heavy ideas
          </ModePill>
        </div>

        {mode === "parallel" ? (
          <div className="mt-3 space-y-2">
            {split.map((entry, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-border bg-bg p-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <input
                    value={entry.engineer_id}
                    onChange={(e) =>
                      patchSplitEntry(idx, { engineer_id: e.target.value })
                    }
                    className="w-28 rounded border border-border bg-bg-card px-2 py-0.5 font-mono"
                  />
                  <span className="text-text-muted">
                    est {fmtTokens(entry.est_tokens)}
                  </span>
                  <button
                    onClick={() => removeEngineer(idx)}
                    className="rounded bg-bg-hover px-2 py-0.5 text-danger hover:bg-danger/20"
                  >
                    remove
                  </button>
                </div>
                <label className="mt-1 block text-[11px] uppercase tracking-wide text-text-muted">
                  idea ids
                </label>
                <input
                  value={entry.idea_ids.join(", ")}
                  onChange={(e) =>
                    patchSplitEntry(idx, {
                      idea_ids: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  className="mt-0.5 w-full rounded border border-border bg-bg-card px-2 py-1 font-mono"
                />
                <label className="mt-1 block text-[11px] uppercase tracking-wide text-text-muted">
                  primary files
                </label>
                <input
                  value={(entry.primary_files ?? []).join(", ")}
                  onChange={(e) =>
                    patchSplitEntry(idx, {
                      primary_files: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  className="mt-0.5 w-full rounded border border-border bg-bg-card px-2 py-1 font-mono"
                />
              </div>
            ))}
            <button
              onClick={addEngineer}
              className="rounded-lg border border-dashed border-border px-3 py-1 text-xs text-text-muted hover:border-accent hover:text-accent"
            >
              + engineer
            </button>
          </div>
        ) : null}

        {mode === "extend_cap" ? (
          <div className="mt-3 flex items-center gap-2 text-xs">
            <label className="text-text-muted">New cap (tokens):</label>
            <input
              type="number"
              value={extendedCap}
              onChange={(e) => setExtendedCap(Number(e.target.value))}
              className="w-32 rounded border border-border bg-bg-card px-2 py-1 font-mono"
            />
            <span className="text-text-muted">
              was {fmtTokens(DEFAULT_CAP)}, estimator forecasts {fmtTokens(totalSingle)}
            </span>
          </div>
        ) : null}
      </section>

      <textarea
        rows={2}
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder="Optional note on decision, or required changes for revise..."
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
      />

      {error ? (
        <p className="text-xs text-danger">Error: {error}</p>
      ) : null}

      {confirming === "approve" ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-success/40 bg-success/10 px-3 py-2">
          <span className="text-xs text-success">Confirm: {approveLabel}?</span>
          <button
            onClick={onApproveClick}
            disabled={busy}
            className="rounded-lg bg-success px-3 py-1 text-xs font-semibold text-bg hover:bg-success/90 disabled:opacity-50"
          >
            {busy ? "Sending…" : "✓ Confirm"}
          </button>
          <button
            onClick={() => setConfirming(null)}
            disabled={busy}
            className="rounded-lg bg-bg-hover px-3 py-1 text-xs text-text-muted hover:text-text"
          >
            Cancel
          </button>
        </div>
      ) : confirming === "revise" ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2">
          <span className="text-xs text-warning">
            Confirm: send feedback back to the estimator?
          </span>
          <button
            onClick={onReviseClick}
            disabled={busy || !feedback.trim()}
            className="rounded-lg bg-warning px-3 py-1 text-xs font-semibold text-bg hover:bg-warning/90 disabled:opacity-50"
          >
            {busy ? "Sending…" : "✓ Confirm revise"}
          </button>
          <button
            onClick={() => setConfirming(null)}
            disabled={busy}
            className="rounded-lg bg-bg-hover px-3 py-1 text-xs text-text-muted hover:text-text"
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setConfirming("approve")}
            disabled={!gate.ready || busy}
            className="rounded-lg bg-success/20 px-3 py-1.5 text-xs font-medium text-success hover:bg-success/30 disabled:opacity-50"
          >
            {approveLabel}…
          </button>
          <button
            onClick={() => setConfirming("revise")}
            disabled={!gate.ready || busy || !feedback.trim()}
            className="rounded-lg bg-warning/20 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/30 disabled:opacity-50"
          >
            Request changes…
          </button>
          {!gate.ready ? (
            <span className="text-[10px] italic text-text-muted">
              Waiting on estimate-implement to complete.
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded border border-border bg-bg-card px-2 py-1">
      <p className="text-[10px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className={`text-sm font-mono ${warn ? "text-danger" : "text-text"}`}>{value}</p>
    </div>
  );
}

function ModePill({
  mode,
  active,
  onClick,
  children,
}: {
  mode: BudgetMode;
  active: BudgetMode;
  onClick: (m: BudgetMode) => void;
  children: React.ReactNode;
}) {
  const isActive = active === mode;
  return (
    <button
      onClick={() => onClick(mode)}
      className={`rounded-lg border px-3 py-1 text-xs font-medium ${
        isActive
          ? "border-accent bg-accent/20 text-accent"
          : "border-border bg-bg-card text-text-muted hover:text-text"
      }`}
    >
      {children}
    </button>
  );
}
