import type { AgentInstance } from "../../types/api";

const statusBadge: Record<string, string> = {
  assigned: "badge-assigned",
  running: "badge-running",
  idle: "badge-pending",
  terminated: "badge-terminated",
};

interface Props {
  instances: AgentInstance[];
  onTerminate: (id: string) => void;
}

export default function InstanceList({ instances, onTerminate }: Props) {
  if (!instances.length) {
    return <p className="text-sm text-text-muted">No agent instances.</p>;
  }

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
            <tr key={inst.id} className="border-t border-border/50 hover:bg-bg-hover/50">
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
                {inst.status !== "terminated" && (
                  <button
                    onClick={() => onTerminate(inst.id)}
                    className="text-xs text-danger hover:text-red-300"
                  >
                    Terminate
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
