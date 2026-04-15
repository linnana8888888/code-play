import { useState, useEffect } from "react";
import { runPipeline } from "../../api/client";
import type { Project } from "../../types/api";

const pipelines = [
  {
    name: "full-game",
    label: "Full Game Pipeline",
    description: "Design, develop, test, and deploy a complete game",
    steps: ["game-designer", "frontend-developer", "qa-tester", "devops-engineer"],
  },
  {
    name: "art-pipeline",
    label: "Art Pipeline",
    description: "Generate concept art, 3D models, and animations",
    steps: ["concept-artist", "3d-modeler", "animator"],
  },
  {
    name: "qa-sweep",
    label: "QA Sweep",
    description: "Run all QA agents across the project",
    steps: ["qa-tester", "performance-tester", "security-auditor"],
  },
];

interface Props {
  projects: Project[];
}

export default function PipelineLauncher({ projects }: Props) {
  const [launching, setLaunching] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState("");

  useEffect(() => {
    if (!selectedProject && projects.length) setSelectedProject(projects[0].id);
  }, [projects, selectedProject]);

  const handleLaunch = async (name: string) => {
    if (!selectedProject) return;
    setLaunching(name);
    try {
      await runPipeline(name, selectedProject);
    } catch {
      /* toast error */
    }
    setLaunching(null);
  };

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
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
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {pipelines.map((p) => (
          <div key={p.name} className="rounded-xl border border-border bg-bg-card p-4">
            <h3 className="font-medium">{p.label}</h3>
            <p className="mt-1 text-xs text-text-muted">{p.description}</p>
            <div className="mt-3 flex flex-wrap gap-1">
              {p.steps.map((s) => (
                <span key={s} className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted">
                  {s}
                </span>
              ))}
            </div>
            <button
              onClick={() => handleLaunch(p.name)}
              disabled={launching === p.name || !selectedProject}
              className="mt-4 w-full rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            >
              {launching === p.name ? "Launching..." : "Launch"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
