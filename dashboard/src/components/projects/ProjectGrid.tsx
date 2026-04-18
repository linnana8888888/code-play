import { useState } from "react";
import { Link } from "react-router-dom";
import type { Project } from "../../types/api";

interface Props {
  projects: Project[];
  onCreate: () => void;
  onDelete?: (id: string) => Promise<void>;
  onCleanup?: () => Promise<{ count: number; deleted?: Array<{ project_id: string }> }>;
  onPreviewCleanup?: () => Promise<{
    count: number;
    would_delete?: Array<{ id: string; name: string; created_at: string }>;
  }>;
}

export default function ProjectGrid({
  projects,
  onCreate,
  onDelete,
  onCleanup,
  onPreviewCleanup,
}: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [cleaning, setCleaning] = useState(false);

  const handleDelete = async (e: React.MouseEvent, p: Project) => {
    e.preventDefault();
    e.stopPropagation();
    if (!onDelete) return;
    const ok = window.confirm(`Delete project "${p.name}"?\n\nThis removes all tasks, messages, memory, and files on disk. Cannot be undone.`);
    if (!ok) return;
    setBusy(p.id);
    try {
      await onDelete(p.id);
    } catch (err) {
      alert(`Delete failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  const handleCleanup = async () => {
    if (!onCleanup || !onPreviewCleanup) return;
    setCleaning(true);
    try {
      const preview = await onPreviewCleanup();
      if (!preview.count) {
        alert("Nothing to clean up — no empty projects found.");
        return;
      }
      const names = (preview.would_delete ?? []).slice(0, 10).map((d) => `• ${d.name}`).join("\n");
      const more = preview.count > 10 ? `\n…and ${preview.count - 10} more` : "";
      const ok = window.confirm(
        `Delete ${preview.count} empty project${preview.count === 1 ? "" : "s"}?\n\n${names}${more}\n\nThis cannot be undone.`,
      );
      if (!ok) return;
      await onCleanup();
    } catch (err) {
      alert(`Cleanup failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Projects</h2>
        <div className="flex items-center gap-2">
          {onCleanup && (
            <button
              onClick={handleCleanup}
              disabled={cleaning}
              className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-text-muted hover:border-accent/40 hover:text-text transition-colors disabled:opacity-50"
              title="Delete all empty projects (no tasks, no memory)"
            >
              {cleaning ? "Cleaning…" : "Clean up empty"}
            </button>
          )}
          <button
            onClick={onCreate}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors"
          >
            + New Project
          </button>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((p) => (
          <div
            key={p.id}
            className="group relative rounded-xl border border-border bg-bg-card p-4 transition-colors hover:border-accent/40"
          >
            {onDelete && (
              <button
                onClick={(e) => handleDelete(e, p)}
                disabled={busy === p.id}
                className="absolute top-2 right-2 rounded px-1.5 py-0.5 text-xs text-text-muted opacity-0 group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-400 transition-opacity disabled:opacity-50"
                title="Delete project"
                aria-label={`Delete ${p.name}`}
              >
                {busy === p.id ? "…" : "✕"}
              </button>
            )}
            <Link to={`/projects/${p.id}`} className="block">
              <h3 className="font-medium pr-6 group-hover:text-accent-hover">{p.name}</h3>
              <p className="mt-1 text-sm text-text-muted line-clamp-2">{p.description}</p>
              <div className="mt-3 flex items-center gap-2 text-xs text-text-muted">
                <span className="badge badge-running">{p.tech_stack || "general"}</span>
                {p.goal && <span className="truncate">{p.goal}</span>}
              </div>
            </Link>
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
          </div>
        ))}
        {projects.length === 0 && (
          <p className="col-span-full text-sm text-text-muted">No projects yet. Create one to get started.</p>
        )}
      </div>
    </div>
  );
}
