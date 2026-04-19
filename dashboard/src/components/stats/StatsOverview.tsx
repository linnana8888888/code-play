import { useEffect, useState } from "react";
import { getStats } from "../../api/client";
import type { Stats } from "../../types/api";

function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div
      className="rounded-2xl border border-border bg-bg-card p-5"
      style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
    >
      <p className="mono-label">{label}</p>
      <p
        className="mt-2 text-[32px] font-semibold leading-none tight-display text-text"
        style={accent ? { color: "var(--color-accent-hover)" } : undefined}
      >
        {value}
      </p>
    </div>
  );
}

export default function StatsOverview() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  if (!stats) return <div className="text-text-muted text-sm">Loading stats…</div>;

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard label="Projects" value={stats.projects} />
      <StatCard label="Agent Definitions" value={stats.agents.definitions} />
      <StatCard label="Running Agents" value={stats.agents.running} accent />
      <StatCard label="Agent Instances" value={stats.agents.instances} />
    </div>
  );
}
