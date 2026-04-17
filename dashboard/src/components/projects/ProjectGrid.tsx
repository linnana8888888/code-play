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
            {p.repo_url && (
              <a
                href={p.repo_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
              >
                <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2 .37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                repo
              </a>
            )}
          </Link>
        ))}
        {projects.length === 0 && (
          <p className="col-span-full text-sm text-text-muted">No projects yet. Create one to get started.</p>
        )}
      </div>
    </div>
  );
}
