import { useEffect, useState } from "react";
import { getStats } from "../../api/client";
import type { Stats } from "../../types/api";

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="rounded-xl border border-border bg-bg-card p-4">
      <p className="text-sm text-text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${color}`}>{value}</p>
    </div>
  );
}

export default function StatsOverview() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  if (!stats) return <div className="text-text-muted text-sm">Loading stats...</div>;

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard label="Projects" value={stats.projects} color="text-accent" />
      <StatCard label="Agent Definitions" value={stats.agents.definitions} color="text-info" />
      <StatCard label="Running Agents" value={stats.agents.running} color="text-success" />
      <StatCard label="Agent Instances" value={stats.agents.instances} color="text-text" />
    </div>
  );
}
