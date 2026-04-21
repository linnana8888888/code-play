import { useState } from "react";
import type { AgentInstance } from "../../types/api";

const statusBadge: Record<string, string> = {
  assigned: "badge-assigned",
  running: "badge-running",
  idle: "badge-pending",
  terminated: "badge-terminated",
  completed: "badge-terminated",
  failed: "badge-terminated",
};

const FINISHED = new Set(["terminated", "completed", "failed"]);

interface Props {
  instances: AgentInstance[];
  onTerminate: (id: string) => void;
  onSweep?: () => void;
}

function AgentRow({ inst, onTerminate }: { inst: AgentInstance; onTerminate: (id: string) => void }) {
  return (
    <tr className="border-t border-border/50 hover:bg-bg-hover/50">
      <td className="px-4 py-2 font-mono text-xs">{inst.id}</td>
      <td className="px-4 py-2">{inst.agent_type}</td>
      <td className="px-4 py-2">
        <span className={`badge ${statusBadge[inst.status] || "badge-blocked"}`}>
          {inst.status}
        </span>
      </td>
      <td className="px-4 py-2 tabular-nums">
        {(inst.tokens_used ?? 0).toLocaleString()}
        {inst.budget_max_tokens ? ` / ${inst.budget_max_tokens.toLocaleString()}` : ""}
      </td>
      <td className="px-4 py-2 tabular-nums">
        ${(inst.cost_usd ?? 0).toFixed(4)}
        {inst.budget_max_usd ? ` / $${inst.budget_max_usd.toFixed(2)}` : ""}
      </td>
      <td className="px-4 py-2">
        {!FINISHED.has(inst.status) && (
          <button
            onClick={() => onTerminate(inst.id)}
            className="text-xs text-danger hover:text-red-300"
          >
            Terminate
          </button>
        )}
      </td>
    </tr>
  );
}

function AgentTable({ instances, onTerminate }: { instances: AgentInstance[]; onTerminate: (id: string) => void }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead className="bg-bg-card text-left text-xs text-text-muted">
          <tr>
            <th className="px-4 py-2">ID</th>
            <th className="px-4 py-2">Type</th>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2">Tokens</th>
            <th className="px-4 py-2">Cost</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          {instances.map((inst) => (
            <AgentRow key={inst.id} inst={inst} onTerminate={onTerminate} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function InstanceList({ instances, onTerminate, onSweep }: Props) {
  const [showFinished, setShowFinished] = useState(false);

  const active = instances.filter((i) => !FINISHED.has(i.status));
  const finished = instances.filter((i) => FINISHED.has(i.status));
  const totalCost = finished.reduce((s, i) => s + (i.cost_usd ?? 0), 0);
  const totalTokens = finished.reduce((s, i) => s + (i.tokens_used ?? 0), 0);

  return (
    <div className="space-y-4">
      {active.length > 0 ? (
        <AgentTable instances={active} onTerminate={onTerminate} />
      ) : (
        <p className="text-sm text-text-muted">No active agents.</p>
      )}

      {finished.length > 0 && (
        <div className="rounded-xl border border-border/50 bg-bg-card/50 p-3">
          <div className="flex items-center justify-between">
            <button
              onClick={() => setShowFinished(!showFinished)}
              className="flex items-center gap-2 text-sm text-text-muted hover:text-text"
            >
              <span className="text-xs">{showFinished ? "▼" : "▶"}</span>
              {finished.length} finished agent{finished.length !== 1 ? "s" : ""}
              <span className="text-xs opacity-60">
                ({totalTokens.toLocaleString()} tokens · ${totalCost.toFixed(4)})
              </span>
            </button>
            {onSweep && (
              <button
                onClick={onSweep}
                className="text-xs text-text-muted hover:text-danger"
              >
                Clear
              </button>
            )}
          </div>
          {showFinished && (
            <div className="mt-3">
              <AgentTable instances={finished} onTerminate={onTerminate} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
