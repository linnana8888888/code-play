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
    <header
      className="sticky top-0 z-10 flex h-16 shrink-0 items-center justify-between border-b border-border bg-white/80 px-8"
      style={{ backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)" }}
    >
      <div className="flex items-center gap-5 text-[13px]">
        {stats ? (
          <>
            <span className="flex items-baseline gap-1.5">
              <span className="font-semibold text-text tight-heading">{stats.projects}</span>
              <span className="mono-label">Projects</span>
            </span>
            <span className="h-3 w-px bg-border-strong" />
            <span className="flex items-baseline gap-1.5">
              <span className="font-semibold text-text tight-heading">{stats.agents.definitions}</span>
              <span className="mono-label">Agents</span>
            </span>
            <span className="h-3 w-px bg-border-strong" />
            <span className="flex items-baseline gap-1.5">
              <span className="font-semibold tight-heading" style={{ color: "var(--color-accent-hover)" }}>
                {stats.agents.running}
              </span>
              <span className="mono-label">Running</span>
            </span>
          </>
        ) : (
          <span className="mono-label">Loading…</span>
        )}
      </div>
      <div
        className="flex items-center gap-2 rounded-full border border-border-strong px-3 py-1"
      >
        <span
          className="inline-flex h-1.5 w-1.5 rounded-full animate-pulse"
          style={{ background: "var(--color-accent)" }}
        />
        <span className="mono-label" style={{ color: "var(--color-text)" }}>Live</span>
      </div>
    </header>
  );
}
