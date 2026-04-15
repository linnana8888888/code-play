import { useEffect, useState } from "react";
import { getStats } from "../../api/client";
import type { Stats } from "../../types/api";

export default function Header() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    const t = setInterval(() => getStats().then(setStats).catch(() => {}), 10_000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-bg-card px-6">
      <div className="text-sm text-text-muted">
        {stats ? (
          <span className="flex gap-4">
            <span>{stats.projects} projects</span>
            <span className="text-border">|</span>
            <span>{stats.agents.definitions} agents</span>
            <span className="text-border">|</span>
            <span className="text-success">{stats.agents.running} running</span>
          </span>
        ) : (
          "Loading..."
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-flex h-2 w-2 rounded-full bg-success animate-pulse" />
        <span className="text-xs text-text-muted">Live</span>
      </div>
    </header>
  );
}
