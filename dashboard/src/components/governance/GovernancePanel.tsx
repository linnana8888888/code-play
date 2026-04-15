import { useGovernance } from "../../hooks/useGovernance";

export default function GovernancePanel() {
  const { approvals, log, skills, loading } = useGovernance();

  if (loading) return <p className="text-sm text-text-muted">Loading...</p>;

  return (
    <div className="space-y-6">
      {/* Pending Approvals */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">Pending Approvals</h2>
        {approvals.filter((a) => a.status === "pending").length === 0 ? (
          <p className="text-sm text-text-muted">No pending approvals.</p>
        ) : (
          <div className="space-y-2">
            {approvals
              .filter((a) => a.status === "pending")
              .map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between rounded-xl border border-border bg-bg-card p-4"
                >
                  <div>
                    <p className="font-medium">{a.tool_or_skill}</p>
                    <p className="text-xs text-text-muted">
                      Requested by {a.agent_id}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button className="rounded-lg bg-success/20 px-3 py-1 text-xs font-medium text-success hover:bg-success/30">
                      Approve
                    </button>
                    <button className="rounded-lg bg-danger/20 px-3 py-1 text-xs font-medium text-danger hover:bg-danger/30">
                      Deny
                    </button>
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>

      {/* Skills */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">Skills</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {skills.map((s) => (
            <div key={s.id} className="rounded-xl border border-border bg-bg-card p-4">
              <p className="font-medium">{s.name}</p>
              <p className="mt-1 text-xs text-text-muted">{s.description}</p>
              <span className="mt-2 inline-block rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted">
                {s.category}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Audit Log */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">Audit Log</h2>
        <div className="max-h-64 overflow-y-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-bg-card text-left text-xs text-text-muted sticky top-0">
              <tr>
                <th className="px-4 py-2">Time</th>
                <th className="px-4 py-2">Agent</th>
                <th className="px-4 py-2">Tool</th>
                <th className="px-4 py-2">Decision</th>
              </tr>
            </thead>
            <tbody>
              {log.map((entry, i) => (
                <tr key={i} className="border-t border-border/50">
                  <td className="px-4 py-1.5 text-xs text-text-muted">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </td>
                  <td className="px-4 py-1.5 font-mono text-xs">{entry.agent_id}</td>
                  <td className="px-4 py-1.5">{entry.tool}</td>
                  <td className="px-4 py-1.5">
                    <span
                      className={`badge ${
                        entry.decision === "allowed"
                          ? "badge-done"
                          : entry.decision === "blocked"
                            ? "badge-terminated"
                            : "badge-pending"
                      }`}
                    >
                      {entry.decision}
                    </span>
                  </td>
                </tr>
              ))}
              {log.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-4 text-center text-text-muted">
                    No governance events yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
