import { Link } from "react-router-dom";
import type { Project } from "../../types/api";

interface Props {
  projects: Project[];
  onCreate: () => void;
}

export default function ProjectGrid({ projects, onCreate }: Props) {
  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Projects</h2>
        <button
          onClick={onCreate}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors"
        >
          + New Project
        </button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((p) => (
          <Link
            key={p.id}
            to={`/projects/${p.id}`}
            className="group rounded-xl border border-border bg-bg-card p-4 transition-colors hover:border-accent/40"
          >
            <h3 className="font-medium group-hover:text-accent-hover">{p.name}</h3>
            <p className="mt-1 text-sm text-text-muted line-clamp-2">{p.description}</p>
            <div className="mt-3 flex items-center gap-2 text-xs text-text-muted">
              <span className="badge badge-running">{p.tech_stack || "general"}</span>
              {p.goal && <span className="truncate">{p.goal}</span>}
            </div>
          </Link>
        ))}
        {projects.length === 0 && (
          <p className="col-span-full text-sm text-text-muted">No projects yet. Create one to get started.</p>
        )}
      </div>
    </div>
  );
}
