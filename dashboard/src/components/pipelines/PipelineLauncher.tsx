import { useEffect, useState } from "react";
import { getPipelines, runPipeline } from "../../api/client";
import type { Project, PipelineDef } from "../../types/api";

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
        <h2 className="text-lg font-semibold">Pipelines</h2>
        <select
          className="rounded-lg border border-border bg-bg px-2 py-1 text-sm text-text outline-none"
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
          className="min-w-[320px] flex-1 rounded-lg border border-border bg-bg px-3 py-1 text-sm outline-none"
        />
      </div>
      {message && (
        <div
          className={`mb-3 rounded-lg border px-3 py-2 text-sm ${
            message.kind === "ok"
              ? "border-green-500/40 bg-green-500/10 text-green-300"
              : "border-red-500/40 bg-red-500/10 text-red-300"
          }`}
        >
          {message.text}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {pipelines.length === 0 && (
          <p className="text-sm text-text-muted">No pipelines configured.</p>
        )}
        {pipelines.map((p) => (
          <div key={p.id} className="rounded-xl border border-border bg-bg-card p-4">
            <h3 className="font-medium">{p.name}</h3>
            <p className="mt-1 text-xs text-text-muted">{p.description}</p>
            <div className="mt-3 flex flex-wrap gap-1">
              {p.steps.map((s) => (
                <span
                  key={s.id}
                  className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted"
                  title={`${s.id} → ${s.agent ?? s.type}`}
                >
                  {s.agent ?? s.type ?? s.id}
                </span>
              ))}
            </div>
            <button
              onClick={() => handleLaunch(p.id)}
              disabled={launching === p.id || !selectedProject}
              className="mt-4 w-full rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              {launching === p.id ? "Launching..." : "Launch"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
