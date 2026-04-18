import { useMemo, useState } from "react";
import { useProposals } from "../../hooks/useProposals";
import type { AgentProposal } from "../../types/api";

export default function PendingRosters() {
  const { pendingBatches, approveBatch, rejectBatch, approveOne, rejectOne } =
    useProposals();
  const [keepSets, setKeepSets] = useState<Record<string, Set<string>>>({});

  function isKept(batchId: string, proposalId: string) {
    const set = keepSets[batchId];
    if (!set) return true; // default = all kept
    return set.has(proposalId);
  }

  function toggle(batchId: string, proposalId: string, all: AgentProposal[]) {
    setKeepSets((prev) => {
      const current = prev[batchId] ?? new Set(all.map((p) => p.id));
      const next = new Set(current);
      if (next.has(proposalId)) next.delete(proposalId);
      else next.add(proposalId);
      return { ...prev, [batchId]: next };
    });
  }

  async function onApproveBatch(batchId: string) {
    const set = keepSets[batchId];
    const keep = set ? Array.from(set) : undefined;
    await approveBatch(batchId, { keep });
    setKeepSets((prev) => {
      const { [batchId]: _drop, ...rest } = prev;
      return rest;
    });
  }

  const kickoffBatches = useMemo(
    () => pendingBatches.filter((b) => b.proposals[0]?.phase === "kickoff"),
    [pendingBatches],
  );
  const inFlightBatches = useMemo(
    () => pendingBatches.filter((b) => b.proposals[0]?.phase === "in_flight"),
    [pendingBatches],
  );

  if (pendingBatches.length === 0) {
    return (
      <div>
        <h2 className="mb-2 text-lg font-semibold">Pending Rosters</h2>
        <p className="text-sm text-text-muted">
          No pending agent roster proposals.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">
        Pending Rosters ({pendingBatches.length})
      </h2>

      {kickoffBatches.length > 0 && (
        <div className="mb-4 space-y-3">
          <p className="text-xs uppercase tracking-wide text-text-muted">
            Kickoff batches
          </p>
          {kickoffBatches.map(({ batch_id, proposals }) => (
            <div
              key={batch_id}
              className="rounded-xl border border-accent/40 bg-bg-card p-4"
            >
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold">
                    Project{" "}
                    <span className="font-mono">{proposals[0].project_id}</span>
                  </p>
                  <p className="text-xs text-text-muted">
                    Proposed by {proposals[0].proposer} ·{" "}
                    {proposals.length} agents
                  </p>
                </div>
                <span className="rounded bg-accent/15 px-2 py-0.5 text-[10px] uppercase text-accent">
                  kickoff
                </span>
              </div>
              <ul className="space-y-1.5">
                {proposals.map((p) => (
                  <li
                    key={p.id}
                    className="flex items-start gap-2 rounded border border-border bg-bg p-2"
                  >
                    <input
                      type="checkbox"
                      checked={isKept(batch_id, p.id)}
                      onChange={() => toggle(batch_id, p.id, proposals)}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <p className="font-mono text-xs font-medium">
                        {p.agent_type}
                      </p>
                      {p.rationale && (
                        <p className="mt-0.5 text-[11px] text-text-muted">
                          {p.rationale}
                        </p>
                      )}
                      {p.model_override && (
                        <p className="mt-0.5 text-[10px] text-text-muted">
                          model: {p.model_override}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => onApproveBatch(batch_id)}
                  className="rounded-lg bg-success/20 px-3 py-1 text-xs font-semibold text-success hover:bg-success/30"
                >
                  Approve batch
                </button>
                <button
                  onClick={() => rejectBatch(batch_id, "rejected from dashboard")}
                  className="rounded-lg bg-danger/20 px-3 py-1 text-xs font-semibold text-danger hover:bg-danger/30"
                >
                  Reject all
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {inFlightBatches.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-text-muted">
            In-flight proposals
          </p>
          {inFlightBatches.flatMap(({ proposals }) =>
            proposals.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between rounded-xl border border-border bg-bg-card p-3"
              >
                <div>
                  <p className="text-sm font-medium font-mono">
                    {p.agent_type}
                  </p>
                  <p className="text-xs text-text-muted">
                    Project {p.project_id} · proposer {p.proposer}
                  </p>
                  {p.rationale && (
                    <p className="mt-1 text-[11px] text-text-muted">
                      {p.rationale}
                    </p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => approveOne(p.id)}
                    className="rounded-lg bg-success/20 px-3 py-1 text-xs font-medium text-success hover:bg-success/30"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => rejectOne(p.id)}
                    className="rounded-lg bg-danger/20 px-3 py-1 text-xs font-medium text-danger hover:bg-danger/30"
                  >
                    Reject
                  </button>
                </div>
              </div>
            )),
          )}
        </div>
      )}
    </div>
  );
}
