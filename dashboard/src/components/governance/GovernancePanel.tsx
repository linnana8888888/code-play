import { useMemo, useState } from "react";
import { useGovernance } from "../../hooks/useGovernance";
import type { Skill, ToolCatalogEntry } from "../../types/api";

const TIER_ORDER: Array<ToolCatalogEntry["tier"]> = [
  "builtin",
  "pre_approved",
  "restricted",
  "blocked",
  "unconfigured",
];

const TIER_LABEL: Record<ToolCatalogEntry["tier"], string> = {
  builtin: "Builtin",
  pre_approved: "Pre-approved",
  restricted: "Restricted",
  blocked: "Blocked",
  unconfigured: "Unconfigured",
};

const TIER_STYLE: Record<ToolCatalogEntry["tier"], string> = {
  builtin: "bg-success/15 text-success border-success/30",
  pre_approved: "bg-accent/15 text-accent border-accent/30",
  restricted: "bg-warning/15 text-warning border-warning/30",
  blocked: "bg-danger/15 text-danger border-danger/30",
  unconfigured: "bg-bg-hover text-text-muted border-border",
};

type OriginFilter = "all" | "native" | "mcp";

export default function GovernancePanel() {
  const { approvals, log, skills, tools, loading } = useGovernance();
  const [search, setSearch] = useState("");
  const [origin, setOrigin] = useState<OriginFilter>("all");

  const counts = useMemo(() => {
    const native = tools.filter((t) => !t.mcp_server).length;
    const mcp = tools.filter((t) => !!t.mcp_server).length;
    return { native, mcp, all: tools.length };
  }, [tools]);

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = tools
      .filter((t) => {
        if (origin === "native") return !t.mcp_server;
        if (origin === "mcp") return !!t.mcp_server;
        return true;
      })
      .filter(
        (t) =>
          !q ||
          t.name.toLowerCase().includes(q) ||
          t.description.toLowerCase().includes(q) ||
          t.agents.some((a) => a.toLowerCase().includes(q)) ||
          (t.source ?? "").toLowerCase().includes(q) ||
          (t.mcp_server ?? "").toLowerCase().includes(q),
      );
    const map = new Map<ToolCatalogEntry["tier"], ToolCatalogEntry[]>();
    for (const t of filtered) {
      if (!map.has(t.tier)) map.set(t.tier, []);
      map.get(t.tier)!.push(t);
    }
    return TIER_ORDER.filter((tier) => map.has(tier)).map((tier) => ({
      tier,
      entries: map.get(tier)!,
    }));
  }, [tools, search, origin]);

  if (loading) return <p className="text-sm text-text-muted">Loading...</p>;

  return (
    <div className="space-y-6">
      {/* Tool Catalog */}
      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold">Tool Catalog</h2>
            <div className="flex gap-1 rounded-lg border border-border bg-bg-card p-0.5">
              {(["all", "native", "mcp"] as OriginFilter[]).map((o) => (
                <button
                  key={o}
                  onClick={() => setOrigin(o)}
                  className={`rounded-md px-2 py-0.5 text-xs font-medium transition ${
                    origin === o
                      ? "bg-accent text-white"
                      : "text-text-muted hover:text-text"
                  }`}
                >
                  {o === "all"
                    ? `All (${counts.all})`
                    : o === "native"
                      ? `Native (${counts.native})`
                      : `MCP (${counts.mcp})`}
                </button>
              ))}
            </div>
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter tools, agents, plugins..."
            className="w-72 max-w-full rounded-lg border border-border bg-bg px-3 py-1 text-sm outline-none"
          />
        </div>
        {tools.length === 0 ? (
          <p className="text-sm text-text-muted">No tools registered.</p>
        ) : grouped.length === 0 ? (
          <p className="text-sm text-text-muted">No tools match "{search}".</p>
        ) : (
          <div className="space-y-4">
            {grouped.map(({ tier, entries }) => (
              <div key={tier}>
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className={`rounded border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${TIER_STYLE[tier]}`}
                  >
                    {TIER_LABEL[tier]}
                  </span>
                  <span className="text-xs text-text-muted">
                    {entries.length} tool{entries.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {entries.map((t) => (
                    <div
                      key={t.name}
                      className="rounded-xl border border-border bg-bg-card p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-sm font-medium">{t.name}</p>
                        {t.mcp_server ? (
                          <span
                            title={`From MCP server: ${t.source ?? t.mcp_server}`}
                            className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent"
                          >
                            mcp:{t.mcp_server}
                          </span>
                        ) : !t.has_handler ? (
                          <span
                            title="No handler registered — tier only"
                            className="rounded bg-warning/15 px-1.5 py-0.5 text-[10px] text-warning"
                          >
                            no handler
                          </span>
                        ) : null}
                      </div>
                      {t.description && (
                        <p className="mt-1 line-clamp-3 text-xs text-text-muted">
                          {t.description}
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-1">
                        {t.agents.length === 0 ? (
                          <span className="text-[10px] text-text-muted">
                            {t.mcp_server ? "any agent (pre-approved)" : "no agents"}
                          </span>
                        ) : (
                          t.agents.slice(0, 6).map((a) => (
                            <span
                              key={a}
                              className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted"
                            >
                              {a}
                            </span>
                          ))
                        )}
                        {t.agents.length > 6 && (
                          <span className="text-[10px] text-text-muted">
                            +{t.agents.length - 6}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

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
      <SkillsCatalog skills={skills} />


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

function SkillsCatalog({ skills }: { skills: Skill[] }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of skills) counts.set(s.category, (counts.get(s.category) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [skills]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return skills.filter((s) => {
      if (category !== "all" && s.category !== category) return false;
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q)
      );
    });
  }, [skills, query, category]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Skills ({skills.length})</h2>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter skills..."
          className="w-72 max-w-full rounded-lg border border-border bg-bg px-3 py-1 text-sm outline-none"
        />
      </div>
      {categories.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-1">
          <button
            onClick={() => setCategory("all")}
            className={`rounded-md px-2 py-0.5 text-xs font-medium ${
              category === "all"
                ? "bg-accent text-white"
                : "bg-bg-card text-text-muted hover:text-text"
            }`}
          >
            All ({skills.length})
          </button>
          {categories.map(([cat, n]) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`rounded-md px-2 py-0.5 text-xs font-medium ${
                category === cat
                  ? "bg-accent text-white"
                  : "bg-bg-card text-text-muted hover:text-text"
              }`}
            >
              {cat || "(uncategorised)"} ({n})
            </button>
          ))}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.slice(0, 60).map((s) => (
          <div key={s.id} className="rounded-xl border border-border bg-bg-card p-4">
            <p className="font-medium">{s.name}</p>
            <p className="mt-1 line-clamp-3 text-xs text-text-muted">{s.description}</p>
            <span className="mt-2 inline-block rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted">
              {s.category || "uncategorised"}
            </span>
          </div>
        ))}
      </div>
      {filtered.length > 60 && (
        <p className="mt-2 text-xs text-text-muted">
          Showing first 60 of {filtered.length} matches. Refine the filter to narrow down.
        </p>
      )}
      {filtered.length === 0 && (
        <p className="text-sm text-text-muted">No skills match the current filter.</p>
      )}
    </div>
  );
}
