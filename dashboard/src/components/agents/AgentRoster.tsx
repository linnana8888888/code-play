import type { AgentDefinition } from "../../types/api";

interface Props {
  definitions: AgentDefinition[];
  categories: string[];
  onSpawn: (agentType: string) => void;
}

export default function AgentRoster({ definitions, categories, onSpawn }: Props) {
  return (
    <div className="space-y-6">
      {categories.map((cat) => (
        <div key={cat}>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-text-muted">
            {cat.replace(/-/g, " ")}
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {definitions
              .filter((d) => d.category === cat)
              .map((d) => (
                <div
                  key={d.id}
                  className="flex items-start justify-between rounded-xl border border-border bg-bg-card p-4"
                >
                  <div className="min-w-0">
                    <p className="font-medium truncate">{d.name}</p>
                    <p className="mt-0.5 text-xs text-text-muted">{d.role}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {d.tools.slice(0, 3).map((t) => (
                        <span key={t} className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted">
                          {t}
                        </span>
                      ))}
                      {d.tools.length > 3 && (
                        <span className="text-[10px] text-text-muted">+{d.tools.length - 3}</span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => onSpawn(d.id)}
                    className="ml-3 shrink-0 rounded-lg bg-accent/20 px-2 py-1 text-xs font-medium text-accent hover:bg-accent/30"
                  >
                    Spawn
                  </button>
                </div>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}
