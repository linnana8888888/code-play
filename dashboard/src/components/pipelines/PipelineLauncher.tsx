import { useEffect, useState } from "react";
import { getPipelines, runPipeline } from "../../api/client";
import type { Project, PipelineDef } from "../../types/api";

type StepLike = { id: string; type?: string; agent?: string };

const ROLE_ICON: Record<string, { icon: string; tint: string; label: string }> = {
  "game-designer":               { icon: "🎲", tint: "#fef3c7", label: "Game designer" },
  "style-researcher":            { icon: "🎨", tint: "#fce7f3", label: "Style researcher" },
  "technical-artist":            { icon: "🖌️", tint: "#fce7f3", label: "Technical artist" },
  "tech-lead":                   { icon: "🏗️", tint: "#e0e7ff", label: "Tech lead" },
  "frontend-developer":          { icon: "💻", tint: "#dbeafe", label: "Frontend developer" },
  "telemetry-engineer":          { icon: "📡", tint: "#cffafe", label: "Telemetry engineer" },
  "qa-engineer":                 { icon: "🎮", tint: "#d4fae8", label: "QA engineer" },
  "code-reviewer":               { icon: "🔍", tint: "#e5e7eb", label: "Code reviewer" },
  "rapid-prototyper":            { icon: "⚡", tint: "#fef3c7", label: "Rapid prototyper" },
  "metrics-dashboard-builder":   { icon: "📊", tint: "#e0e7ff", label: "Metrics dashboard builder" },
  "analytics-reporter":          { icon: "📈", tint: "#e0e7ff", label: "Analytics reporter" },
  "publisher":                   { icon: "🚀", tint: "#d4fae8", label: "Publisher" },
  "hud-designer":                { icon: "🎛️", tint: "#fce7f3", label: "HUD designer" },
  "player-feedback-synthesizer": { icon: "💬", tint: "#cffafe", label: "Player feedback" },
  "support-analytics-reporter":  { icon: "📋", tint: "#e0e7ff", label: "Support analytics" },
};

function stepMeta(s: StepLike): { icon: string; tint: string; label: string } {
  if (s.type === "human-gate") return { icon: "✋", tint: "#f5f5f5", label: "Human gate" };
  if (s.agent && ROLE_ICON[s.agent]) return ROLE_ICON[s.agent];
  // propose-* variants
  if (s.id.startsWith("propose-")) return { icon: "💭", tint: "#fce7f3", label: s.id.replace("propose-", "Propose: ") };
  return { icon: "•", tint: "#f5f5f5", label: s.agent ?? s.type ?? s.id };
}

interface Props {
  projects: Project[];
}

export default function PipelineLauncher({ projects }: Props) {
  const [pipelines, setPipelines] = useState<PipelineDef[]>([]);
  const [launching, setLaunching] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState("");
  const [inputText, setInputText] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    getPipelines().then(setPipelines).catch(() => setPipelines([]));
  }, []);

  useEffect(() => {
    if (!selectedProject && projects.length) setSelectedProject(projects[0].id);
  }, [projects, selectedProject]);

  const handleLaunch = async (name: string) => {
    if (!selectedProject) return;
    setLaunching(name);
    setMessage(null);
    try {
      await runPipeline(name, selectedProject, inputText);
      setMessage({ kind: "ok", text: `Launched ${name} — tasks created, check the Task Board.` });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Launch failed";
      setMessage({ kind: "err", text: msg });
    }
    setLaunching(null);
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-[20px] font-semibold tight-heading">Pipelines</h2>
        <select
          className="rounded-full border border-border-strong bg-white px-3 py-1.5 text-sm text-text outline-none"
          value={selectedProject}
          onChange={(e) => setSelectedProject(e.target.value)}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Game concept (fills {input} in pipeline tasks)"
          className="min-w-[320px] flex-1 rounded-full border border-border-strong bg-white px-4 py-1.5 text-sm outline-none placeholder:text-text-subtle focus:border-accent"
        />
      </div>
      {message && (
        <div
          className="mb-3 rounded-2xl border px-4 py-2.5 text-sm"
          style={
            message.kind === "ok"
              ? { borderColor: "var(--color-accent)", background: "var(--color-accent-tint)", color: "var(--color-accent-hover)" }
              : { borderColor: "var(--color-danger)", background: "#fee2e2", color: "#991b1b" }
          }
        >
          {message.text}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {pipelines.length === 0 && (
          <p className="text-sm text-text-muted">No pipelines configured.</p>
        )}
        {pipelines.map((p) => (
          <div
            key={p.id}
            className="rounded-2xl border border-border bg-bg-card p-6"
            style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
          >
            <h3 className="text-[18px] font-semibold tight-heading">{p.name}</h3>
            <p className="mt-1.5 text-sm text-text-muted">{p.description}</p>
            <div className="mt-4 flex items-center gap-1 overflow-x-auto pb-1">
              {p.steps.map((s, i) => {
                const meta = stepMeta(s);
                return (
                  <div key={s.id} className="flex items-center gap-1 shrink-0">
                    {i > 0 && <span className="text-text-subtle" style={{ fontSize: "10px" }}>›</span>}
                    <span
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
                      style={{ background: meta.tint, fontSize: "13px", lineHeight: 1 }}
                      title={`${meta.label} · ${s.id}`}
                    >
                      {meta.icon}
                    </span>
                  </div>
                );
              })}
              <span className="mono-label ml-1 shrink-0" style={{ fontSize: "10px" }}>
                {p.steps.length} steps
              </span>
            </div>
            <button
              onClick={() => handleLaunch(p.id)}
              disabled={launching === p.id || !selectedProject}
              className="btn-primary mt-5 w-full"
            >
              {launching === p.id ? "Launching…" : "Launch pipeline"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
