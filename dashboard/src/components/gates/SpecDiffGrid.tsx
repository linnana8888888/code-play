/*
 * SpecDiffGrid — rendered for the synthesis_gate step in the iterate_artifact
 * pipeline. Shows the 4 proposer outputs (designer / ux / artist / proto) side
 * by side, plus the postmortem and rollup that triggered them, so the human
 * reviewer can pick ONE to implement or revise in a single glance.
 *
 * Trigger: `gate.step_id === "synthesis_gate"` OR `gate.review_of?.startsWith("propose-")`.
 *
 * Data sources (all via the existing /api/projects/{id}/memory endpoint):
 *   - cycle.n                      → current cycle number
 *   - artifact.postmortem_v{n}     → markdown
 *   - artifact.telemetry_v{n}      → JSON rollup (aggregates + outcome_counts)
 *   - artifact.proposal_{role}_v{n}→ markdown (roles: designer, ux, artist, proto)
 *   - artifact.goals_md            → markdown, for reference
 *
 * The component does NOT mutate state; approve/revise is handled by the
 * parent GatesPanel via the callback props. The feedback textarea is
 * controlled there too, so GatesPanel remains the single decision point.
 */
import { useEffect, useState } from "react";
import type { HumanGate } from "../../types/api";
import { getMemory } from "../../api/client";

const ROLES = ["designer", "ux", "artist", "proto"] as const;
type Role = (typeof ROLES)[number];

interface Props {
  projectId: string;
  gate: HumanGate;
  busy: boolean;
  feedback: string;
  onFeedbackChange: (v: string) => void;
  onApprove: () => void;
  onRevise: () => void;
}

type Rollup = {
  cycle_n?: number;
  iteration_tag?: string;
  n_runs?: number;
  n_valid?: number;
  outcome_counts?: Record<string, number>;
  aggregates?: Record<string, { median?: number; p25?: number; p75?: number }>;
};

async function readOrNull(
  projectId: string,
  memType: string,
  key: string,
): Promise<string | null> {
  try {
    const r = await getMemory(projectId, memType, key);
    return r?.content ?? null;
  } catch {
    return null;
  }
}

function parseRollup(raw: string | null): Rollup | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function fmt(n: number | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 100) return n.toFixed(0);
  if (Math.abs(n) >= 10) return n.toFixed(1);
  return n.toFixed(2);
}

function RoleTile({
  role,
  content,
}: {
  role: Role;
  content: string | null;
}) {
  const label = role.charAt(0).toUpperCase() + role.slice(1);
  return (
    <div className="flex min-h-[220px] flex-col rounded-lg border border-border bg-bg p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-accent">
          {label}
        </span>
        <span className="text-[10px] text-text-muted">
          propose-{role}
        </span>
      </div>
      {content ? (
        <pre className="flex-1 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text">
          {content}
        </pre>
      ) : (
        <p className="flex-1 text-[11px] italic text-text-muted">
          proposal not found in memory (key{" "}
          <code>proposal_{role}_v{"{n}"}</code>). The proposer may still be
          running or may have failed — check the task list.
        </p>
      )}
    </div>
  );
}

function RollupSummary({ rollup }: { rollup: Rollup | null }) {
  if (!rollup) {
    return (
      <p className="text-[11px] italic text-text-muted">
        No telemetry rollup found for this cycle.
      </p>
    );
  }
  const agg = rollup.aggregates ?? {};
  const rows: [string, string][] = [
    ["runs", `${rollup.n_valid ?? 0}/${rollup.n_runs ?? 0} valid`],
    [
      "outcomes",
      Object.entries(rollup.outcome_counts ?? {})
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `${k}:${v}`)
        .join(" · ") || "—",
    ],
    ["session_duration_sec (median)", fmt(agg["session_duration_sec"]?.median)],
    ["accuracy (p25/p75)", `${fmt(agg["accuracy"]?.p25)} / ${fmt(agg["accuracy"]?.p75)}`],
    ["levels_reached (median)", fmt(agg["levels_reached"]?.median)],
    ["kills (median)", fmt(agg["kills"]?.median)],
    ["time_to_first_kill_sec (median)", fmt(agg["time_to_first_kill_sec"]?.median)],
    ["dashes_used (median)", fmt(agg["dashes_used"]?.median)],
  ];
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-center justify-between gap-2 text-[11px]">
          <span className="text-text-muted">{k}</span>
          <span className="font-mono text-text">{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function SpecDiffGrid({
  projectId,
  gate,
  busy,
  feedback,
  onFeedbackChange,
  onApprove,
  onRevise,
}: Props) {
  const [cycleN, setCycleN] = useState<number | null>(null);
  const [postmortem, setPostmortem] = useState<string | null>(null);
  const [rollup, setRollup] = useState<Rollup | null>(null);
  const [proposals, setProposals] = useState<Record<Role, string | null>>({
    designer: null,
    ux: null,
    artist: null,
    proto: null,
  });
  const [goals, setGoals] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showGoals, setShowGoals] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      const raw = await readOrNull(projectId, "cycle", "n");
      const n = raw ? parseInt(raw, 10) : null;
      if (cancelled) return;
      setCycleN(n);

      if (n == null || !Number.isFinite(n)) {
        setLoading(false);
        return;
      }

      const tag = `v${n}`;
      const [pm, tel, pd, pu, pa, pp, g] = await Promise.all([
        readOrNull(projectId, "artifact", `postmortem_${tag}`),
        readOrNull(projectId, "artifact", `telemetry_${tag}`),
        readOrNull(projectId, "artifact", `proposal_designer_${tag}`),
        readOrNull(projectId, "artifact", `proposal_ux_${tag}`),
        readOrNull(projectId, "artifact", `proposal_artist_${tag}`),
        readOrNull(projectId, "artifact", `proposal_proto_${tag}`),
        readOrNull(projectId, "artifact", "goals_md"),
      ]);
      if (cancelled) return;
      setPostmortem(pm);
      setRollup(parseRollup(tel));
      setProposals({ designer: pd, ux: pu, artist: pa, proto: pp });
      setGoals(g);
      setLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId, gate.task_id]);

  const tag = cycleN != null ? `v${cycleN}` : "—";
  const missing = ROLES.filter((r) => !proposals[r]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-text-muted">
            {gate.pipeline_label} · step {gate.step_id}
          </p>
          <h3 className="text-base font-semibold">
            Synthesis gate — cycle {tag}
            <span className="ml-2 rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-normal text-accent">
              pick one proposal
            </span>
          </h3>
          <p className="mt-1 text-xs text-text-muted">
            Review the 4 proposals against the postmortem. Note the winner in
            feedback (e.g. <code>pick: designer</code>) and approve to hand off
            to implement. Request changes to send one proposer back. Leave the
            note empty + approve to pass the designer proposal through.
          </p>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-[10px] font-medium ${
            gate.ready ? "bg-success/20 text-success" : "bg-warning/20 text-warning"
          }`}
        >
          {gate.ready ? "ready for review" : "waiting on upstream"}
        </span>
      </div>

      {loading ? (
        <p className="text-xs italic text-text-muted">Loading proposals…</p>
      ) : (
        <>
          {/* Rollup + postmortem pair */}
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-border bg-bg-card p-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                Rollup ({tag})
              </p>
              <RollupSummary rollup={rollup} />
            </div>
            <div className="rounded-lg border border-border bg-bg-card p-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                Postmortem ({tag})
              </p>
              {postmortem ? (
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text">
                  {postmortem}
                </pre>
              ) : (
                <p className="text-[11px] italic text-text-muted">
                  postmortem_{tag} not found in memory.
                </p>
              )}
            </div>
          </div>

          {/* Proposal grid */}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {ROLES.map((r) => (
              <RoleTile key={r} role={r} content={proposals[r]} />
            ))}
          </div>

          {missing.length > 0 ? (
            <p className="text-[11px] text-warning">
              {missing.length} proposer output(s) missing: {missing.join(", ")}.
              The synthesis gate may have opened before every proposer finished
              — refresh in a moment.
            </p>
          ) : null}

          {/* Goals reference (collapsed by default) */}
          <div className="rounded-lg border border-border bg-bg-card p-3">
            <button
              onClick={() => setShowGoals((s) => !s)}
              className="text-[11px] font-semibold uppercase tracking-wide text-text-muted hover:text-text"
            >
              {showGoals ? "▼" : "▶"} GOALS.md (reference)
            </button>
            {showGoals ? (
              goals ? (
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text">
                  {goals}
                </pre>
              ) : (
                <p className="mt-2 text-[11px] italic text-text-muted">
                  goals_md not in memory.
                </p>
              )
            ) : null}
          </div>
        </>
      )}

      {/* Feedback + decision buttons */}
      <textarea
        rows={2}
        value={feedback}
        onChange={(e) => onFeedbackChange(e.target.value)}
        placeholder="Note the winner (e.g. 'pick: designer — strongest accuracy-band claim'). Required for Request changes."
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
      />
      <div className="flex gap-2">
        <button
          disabled={!gate.ready || busy}
          onClick={onApprove}
          className="rounded-lg bg-success/20 px-3 py-1.5 text-xs font-medium text-success hover:bg-success/30 disabled:opacity-50"
        >
          {busy ? "..." : "Approve pick"}
        </button>
        <button
          disabled={!gate.ready || busy || !feedback.trim()}
          onClick={onRevise}
          className="rounded-lg bg-warning/20 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/30 disabled:opacity-50"
        >
          {busy ? "..." : "Request changes"}
        </button>
      </div>
    </div>
  );
}
