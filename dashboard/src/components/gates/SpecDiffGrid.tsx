/*
 * IdeaBoard (exported as SpecDiffGrid for call-site compatibility).
 *
 * Renders the synthesis_gate for iterate_artifact. Each proposer now emits
 * 5-8 structured ideas in a JSON fence inside its `proposal_{role}_{tag}`
 * memory key. We parse all 4 keys, flatten into one list, and let the human
 * multi-select across roles (plus add their own). Approve sends the bundle
 * to the backend which serialises it to `selected_ideas_{tag}` memory; the
 * implement step reads that instead of one monolithic proposal.
 *
 * Falls back to raw-markdown tiles (old monolithic format) when no JSON
 * block parses — keeps pre-schema cycles viewable.
 */
import { useEffect, useMemo, useState } from "react";
import type { HumanGate } from "../../types/api";
import { getMemory } from "../../api/client";

const ROLES = ["designer", "ux", "artist", "proto"] as const;
type Role = (typeof ROLES)[number];

type Idea = {
  id: string;
  role: Role;
  title: string;
  hypothesis?: string;
  expected_impact?: { metric?: string; delta?: string };
  risk?: string;
  change_summary?: string;
};

type CustomIdea = {
  id: string;
  title: string;
  hypothesis: string;
  expected_impact: { metric: string; delta: string };
  risk: string;
  change_summary: string;
};

interface Props {
  projectId: string;
  gate: HumanGate;
  busy: boolean;
  feedback: string;
  onFeedbackChange: (v: string) => void;
  confirming: "approve" | "revise" | null;
  onArmApprove: () => void;
  onArmRevise: () => void;
  onCancelConfirm: () => void;
  onApprove: (bundle: { selected: Idea[]; custom: CustomIdea[] }) => void;
  onRevise: () => void;
}

type Rollup = {
  n_runs?: number;
  n_valid?: number;
  outcome_counts?: Record<string, number>;
  aggregates?: Record<string, { median?: number; p25?: number; p75?: number }>;
};

async function readOrNull(projectId: string, memType: string, key: string): Promise<string | null> {
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

/**
 * Extract 5-8 structured ideas from a proposer memory blob. The prompt tells
 * proposers to wrap ideas in a ```json fence, so we find the first fence and
 * parse it. Accepts either `{role, ideas: [...]}` or a bare `[...]` array for
 * leniency — some models drop the wrapper.
 */
function parseIdeas(raw: string | null, role: Role): Idea[] | null {
  if (!raw) return null;
  const fence = raw.match(/```json\s*([\s\S]*?)```/i);
  const body = (fence?.[1] ?? raw).trim();
  try {
    const parsed: unknown = JSON.parse(body);
    const arr = Array.isArray(parsed)
      ? parsed
      : (parsed as { ideas?: unknown[] })?.ideas;
    if (!Array.isArray(arr)) return null;
    return arr
      .filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null)
      .map((x, i) => ({
        id: typeof x.id === "string" && x.id ? x.id : `${role}-${i + 1}`,
        role,
        title: typeof x.title === "string" ? x.title : "(untitled)",
        hypothesis: typeof x.hypothesis === "string" ? x.hypothesis : undefined,
        expected_impact:
          typeof x.expected_impact === "object" && x.expected_impact !== null
            ? (x.expected_impact as { metric?: string; delta?: string })
            : undefined,
        risk: typeof x.risk === "string" ? x.risk : undefined,
        change_summary: typeof x.change_summary === "string" ? x.change_summary : undefined,
      }));
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

const ROLE_COLORS: Record<Role, { chip: string; border: string }> = {
  designer: { chip: "bg-blue-500/15 text-blue-300", border: "border-blue-500/30" },
  ux: { chip: "bg-purple-500/15 text-purple-300", border: "border-purple-500/30" },
  artist: { chip: "bg-pink-500/15 text-pink-300", border: "border-pink-500/30" },
  proto: { chip: "bg-emerald-500/15 text-emerald-300", border: "border-emerald-500/30" },
};

function IdeaCard({
  idea,
  checked,
  onToggle,
}: {
  idea: Idea;
  checked: boolean;
  onToggle: () => void;
}) {
  const cls = ROLE_COLORS[idea.role];
  return (
    <label
      className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors ${
        checked ? `${cls.border} bg-bg` : "border-border bg-bg-card hover:bg-bg"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-1 h-4 w-4 shrink-0 accent-accent"
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-semibold text-text">{idea.title}</p>
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${cls.chip}`}>
            {idea.role}
          </span>
        </div>
        {idea.hypothesis ? (
          <p className="text-xs text-text-muted">
            <span className="text-text/70">Hypothesis:</span> {idea.hypothesis}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
          {idea.expected_impact?.metric ? (
            <span className="text-success">
              ↑ {idea.expected_impact.metric}
              {idea.expected_impact.delta ? ` ${idea.expected_impact.delta}` : ""}
            </span>
          ) : null}
          {idea.risk ? <span className="text-warning">⚠ {idea.risk}</span> : null}
        </div>
        {idea.change_summary ? (
          <p className="text-[11px] italic text-text-muted">{idea.change_summary}</p>
        ) : null}
        <p className="font-mono text-[10px] text-text-muted/60">{idea.id}</p>
      </div>
    </label>
  );
}

function RollupSummary({ rollup }: { rollup: Rollup | null }) {
  if (!rollup) {
    return <p className="text-[11px] italic text-text-muted">No telemetry rollup for this cycle.</p>;
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
  confirming,
  onArmApprove,
  onArmRevise,
  onCancelConfirm,
  onApprove,
  onRevise,
}: Props) {
  const [cycleN, setCycleN] = useState<number | null>(null);
  const [postmortem, setPostmortem] = useState<string | null>(null);
  const [rollup, setRollup] = useState<Rollup | null>(null);
  const [rawProposals, setRawProposals] = useState<Record<Role, string | null>>({
    designer: null,
    ux: null,
    artist: null,
    proto: null,
  });
  const [goals, setGoals] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showGoals, setShowGoals] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [customIdeas, setCustomIdeas] = useState<CustomIdea[]>([]);
  const [draft, setDraft] = useState<CustomIdea>({
    id: "",
    title: "",
    hypothesis: "",
    expected_impact: { metric: "", delta: "" },
    risk: "",
    change_summary: "",
  });
  const [groupByRole, setGroupByRole] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let firstLoad = true;
    async function load() {
      if (firstLoad) setLoading(true);
      let n = gate.cycle_n ?? null;
      if (n == null) {
        const raw = await readOrNull(projectId, "cycle", "n");
        n = raw ? parseInt(raw, 10) : null;
      }
      if (cancelled) return;
      if (n == null || !Number.isFinite(n)) {
        setCycleN(n);
        setLoading(false);
        return;
      }
      const tryLoad = async (cn: number) => {
        const t = gate.iteration_tag ?? `v${cn}`;
        const [pm, tel, pd, pu, pa, pp, g] = await Promise.all([
          readOrNull(projectId, "artifact", `postmortem_${t}`),
          readOrNull(projectId, "artifact", `telemetry_${t}`),
          readOrNull(projectId, "artifact", `proposal_designer_${t}`),
          readOrNull(projectId, "artifact", `proposal_ux_${t}`),
          readOrNull(projectId, "artifact", `proposal_artist_${t}`),
          readOrNull(projectId, "artifact", `proposal_proto_${t}`),
          readOrNull(projectId, "artifact", "goals_md"),
        ]);
        return { pm, tel, pd, pu, pa, pp, g, cycleN: cn };
      };
      let loaded = await tryLoad(n);
      if (gate.cycle_n == null && !loaded.pd && !loaded.pu && !loaded.pa && !loaded.pp) {
        for (let probe = n - 1; probe >= 1; probe -= 1) {
          const attempt = await tryLoad(probe);
          if (cancelled) return;
          if (attempt.pd || attempt.pu || attempt.pa || attempt.pp) {
            loaded = attempt;
            n = probe;
            break;
          }
        }
      }
      if (cancelled) return;
      setCycleN(n);
      setPostmortem(loaded.pm);
      setRollup(parseRollup(loaded.tel));
      setRawProposals({ designer: loaded.pd, ux: loaded.pu, artist: loaded.pa, proto: loaded.pp });
      setGoals(loaded.g);
      setLoading(false);
      firstLoad = false;
    }
    load();
    const timer = setInterval(() => {
      if (!cancelled) load();
    }, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [projectId, gate.task_id, gate.cycle_n, gate.iteration_tag]);

  const allIdeas = useMemo<Idea[]>(() => {
    const out: Idea[] = [];
    for (const r of ROLES) {
      const parsed = parseIdeas(rawProposals[r], r);
      if (parsed) out.push(...parsed);
    }
    return out;
  }, [rawProposals]);

  const unparsedRoles = useMemo(() => ROLES.filter((r) => rawProposals[r] && !parseIdeas(rawProposals[r], r)), [rawProposals]);
  const missingRoles = useMemo(() => ROLES.filter((r) => !rawProposals[r]), [rawProposals]);
  const tag = cycleN != null ? `v${cycleN}` : "—";
  const selectedIdeas = allIdeas.filter((i) => selectedIds.has(i.id));
  const totalPicked = selectedIdeas.length + customIdeas.length;

  function toggle(id: string) {
    setSelectedIds((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function addCustom() {
    if (!draft.title.trim()) return;
    const id = `human-${customIdeas.length + 1}`;
    setCustomIdeas((xs) => [...xs, { ...draft, id }]);
    setDraft({
      id: "",
      title: "",
      hypothesis: "",
      expected_impact: { metric: "", delta: "" },
      risk: "",
      change_summary: "",
    });
  }

  function removeCustom(id: string) {
    setCustomIdeas((xs) => xs.filter((x) => x.id !== id));
  }

  const approveDisabled = !gate.ready || busy || totalPicked === 0;
  const reviseDisabled = !gate.ready || busy || !feedback.trim();

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
              pick any ideas
            </span>
          </h3>
          <p className="mt-1 text-xs text-text-muted">
            {allIdeas.length} ideas across {ROLES.length} roles. Check the ones
            to implement this cycle (any mix, any count), add your own below,
            and approve. Request changes sends every role back for a fresh batch.
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
        <p className="text-xs italic text-text-muted">Loading ideas…</p>
      ) : (
        <>
          {/* Rollup + postmortem */}
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
                  postmortem_{tag} not in memory.
                </p>
              )}
            </div>
          </div>

          {/* Idea board */}
          {allIdeas.length === 0 ? (
            <div className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs text-warning">
              No structured ideas parsed from any proposer. This cycle may
              predate the JSON-schema prompt — showing raw markdown fallback
              below. Re-run iterate_artifact to get the new idea-board format.
              {unparsedRoles.length > 0 && (
                <p className="mt-1">
                  JSON parse failed for: {unparsedRoles.join(", ")}
                </p>
              )}
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-[11px] text-text-muted">
                  <span>
                    <span className="font-mono text-accent">{totalPicked}</span> selected ·
                    <span className="font-mono"> {allIdeas.length}</span> proposer ideas
                    {customIdeas.length > 0 ? ` · ${customIdeas.length} yours` : ""}
                  </span>
                  {missingRoles.length > 0 && (
                    <span className="text-warning">
                      missing: {missingRoles.join(", ")}
                    </span>
                  )}
                </div>
                <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
                  <input
                    type="checkbox"
                    checked={groupByRole}
                    onChange={(e) => setGroupByRole(e.target.checked)}
                    className="h-3 w-3 accent-accent"
                  />
                  group by role
                </label>
              </div>

              {groupByRole ? (
                <div className="space-y-3">
                  {ROLES.map((r) => {
                    const roleIdeas = allIdeas.filter((i) => i.role === r);
                    if (roleIdeas.length === 0) return null;
                    return (
                      <div key={r} className="space-y-2">
                        <p className={`text-[11px] font-semibold uppercase tracking-wide ${ROLE_COLORS[r].chip.split(" ")[1]}`}>
                          {r} ({roleIdeas.length})
                        </p>
                        <div className="grid gap-2 md:grid-cols-2">
                          {roleIdeas.map((i) => (
                            <IdeaCard
                              key={i.id}
                              idea={i}
                              checked={selectedIds.has(i.id)}
                              onToggle={() => toggle(i.id)}
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="grid gap-2 md:grid-cols-2">
                  {allIdeas.map((i) => (
                    <IdeaCard
                      key={i.id}
                      idea={i}
                      checked={selectedIds.has(i.id)}
                      onToggle={() => toggle(i.id)}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {/* Fallback raw view */}
          {unparsedRoles.length > 0 && (
            <details className="rounded-lg border border-border bg-bg-card p-3">
              <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                ▶ Raw proposals ({unparsedRoles.length} roles with unparsed content)
              </summary>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                {unparsedRoles.map((r) => (
                  <div key={r} className="rounded border border-border bg-bg p-2">
                    <p className={`mb-1 text-[10px] font-semibold uppercase ${ROLE_COLORS[r].chip.split(" ")[1]}`}>
                      {r} (raw)
                    </p>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] text-text">
                      {rawProposals[r]}
                    </pre>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Custom ideas */}
          <div className="rounded-lg border border-border bg-bg-card p-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
              Add your own ideas ({customIdeas.length})
            </p>
            {customIdeas.length > 0 && (
              <div className="mb-3 space-y-1">
                {customIdeas.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-start justify-between gap-2 rounded border border-accent/30 bg-bg p-2 text-[11px]"
                  >
                    <div className="min-w-0">
                      <p className="font-semibold text-text">{c.title}</p>
                      {c.hypothesis && <p className="text-text-muted">{c.hypothesis}</p>}
                      {c.expected_impact.metric && (
                        <p className="text-success">
                          ↑ {c.expected_impact.metric} {c.expected_impact.delta}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => removeCustom(c.id)}
                      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-text-muted hover:bg-bg-hover hover:text-danger"
                    >
                      remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="grid gap-2 md:grid-cols-2">
              <input
                value={draft.title}
                onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
                placeholder="Title (required)"
                className="rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent"
              />
              <input
                value={draft.hypothesis}
                onChange={(e) => setDraft((d) => ({ ...d, hypothesis: e.target.value }))}
                placeholder="Hypothesis"
                className="rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent"
              />
              <input
                value={draft.expected_impact.metric}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    expected_impact: { ...d.expected_impact, metric: e.target.value },
                  }))
                }
                placeholder="Metric (e.g. accuracy)"
                className="rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent"
              />
              <input
                value={draft.expected_impact.delta}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    expected_impact: { ...d.expected_impact, delta: e.target.value },
                  }))
                }
                placeholder="Delta (e.g. +0.05)"
                className="rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent"
              />
              <input
                value={draft.risk}
                onChange={(e) => setDraft((d) => ({ ...d, risk: e.target.value }))}
                placeholder="Risk"
                className="rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent"
              />
              <input
                value={draft.change_summary}
                onChange={(e) => setDraft((d) => ({ ...d, change_summary: e.target.value }))}
                placeholder="Change summary"
                className="rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent"
              />
            </div>
            <button
              onClick={addCustom}
              disabled={!draft.title.trim()}
              className="mt-2 rounded-lg bg-accent/20 px-3 py-1 text-xs font-medium text-accent hover:bg-accent/30 disabled:opacity-50"
            >
              + Add idea
            </button>
          </div>

          {/* Goals ref (collapsed) */}
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
                <p className="mt-2 text-[11px] italic text-text-muted">goals_md not in memory.</p>
              )
            ) : null}
          </div>
        </>
      )}

      {/* Feedback + decision */}
      <textarea
        rows={2}
        value={feedback}
        onChange={(e) => onFeedbackChange(e.target.value)}
        placeholder="Optional note on approve (stored with selection). REQUIRED for Request changes — tell all 4 proposers what to do differently."
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
      />

      {confirming === "approve" ? (
        <div className="space-y-2 rounded-lg border border-success/40 bg-success/10 px-3 py-2">
          <p className="text-xs font-semibold text-success">
            Confirm: hand off {totalPicked} idea{totalPicked === 1 ? "" : "s"} to implement?
          </p>
          <ul className="space-y-1">
            {selectedIdeas.map((i) => (
              <li key={i.id} className="flex items-center gap-2 text-[11px]">
                <span className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-medium ${ROLE_COLORS[i.role].chip}`}>
                  {i.role}
                </span>
                <span className="text-text">{i.title}</span>
                {i.expected_impact?.metric && (
                  <span className="text-success/70">↑ {i.expected_impact.metric}</span>
                )}
              </li>
            ))}
            {customIdeas.map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-[11px]">
                <span className="shrink-0 rounded bg-accent/15 px-1 py-0.5 text-[9px] font-medium text-accent">
                  yours
                </span>
                <span className="text-text">{c.title}</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onApprove({ selected: selectedIdeas, custom: customIdeas })}
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
        </div>
      ) : confirming === "revise" ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2">
          <span className="text-xs text-warning">
            Confirm: send feedback to ALL 4 proposers for a fresh batch?
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
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              disabled={approveDisabled}
              onClick={onArmApprove}
              className="rounded-lg bg-success/20 px-3 py-1.5 text-xs font-medium text-success hover:bg-success/30 disabled:opacity-50"
            >
              Approve {totalPicked} idea{totalPicked === 1 ? "" : "s"}…
            </button>
            <button
              disabled={reviseDisabled}
              onClick={onArmRevise}
              className="rounded-lg bg-warning/20 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/30 disabled:opacity-50"
            >
              Request changes (all roles)…
            </button>
            {!gate.ready && (
              <span className="text-[10px] italic text-text-muted">
                Waiting on upstream — buttons enable when all 4 proposers finish.
              </span>
            )}
            {gate.ready && totalPicked === 0 && (
              <span className="text-[10px] italic text-text-muted">
                Select at least one idea to approve, or add your own above.
              </span>
            )}
          </div>
          {totalPicked > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {selectedIdeas.map((i) => (
                <span
                  key={i.id}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${ROLE_COLORS[i.role].border} ${ROLE_COLORS[i.role].chip}`}
                >
                  {i.role}: {i.title.length > 40 ? i.title.slice(0, 37) + "…" : i.title}
                </span>
              ))}
              {customIdeas.map((c) => (
                <span
                  key={c.id}
                  className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent/15 px-2 py-0.5 text-[10px] text-accent"
                >
                  yours: {c.title.length > 40 ? c.title.slice(0, 37) + "…" : c.title}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
