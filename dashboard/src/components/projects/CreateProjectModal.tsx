import { useState } from "react";
import type { ProjectCreate } from "../../types/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreate: (data: ProjectCreate) => Promise<void>;
}

export default function CreateProjectModal({ open, onClose, onCreate }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [techStack, setTechStack] = useState("threejs");
  const [goal, setGoal] = useState("");
  const [createRepo, setCreateRepo] = useState(false);
  const [rosterApproval, setRosterApproval] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await onCreate({
      name,
      description,
      tech_stack: techStack,
      goal: goal || undefined,
      create_repo: createRepo,
      require_roster_approval: rosterApproval,
    });
    setSubmitting(false);
    setName(""); setDescription(""); setGoal("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-xl border border-border bg-bg-card p-6 space-y-4"
      >
        <h2 className="text-lg font-semibold">New Project</h2>
        <input
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          placeholder="Project name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <textarea
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          placeholder="Description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <select
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none"
          value={techStack}
          onChange={(e) => setTechStack(e.target.value)}
        >
          <option value="threejs">Three.js</option>
          <option value="pixijs">Pixi.js</option>
          <option value="phaser">Phaser</option>
          <option value="babylon">Babylon.js</option>
          <option value="web">Web (HTML/CSS/JS)</option>
        </select>
        <input
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          placeholder="Goal (optional)"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-text-muted">
          <input
            type="checkbox"
            checked={createRepo}
            onChange={(e) => setCreateRepo(e.target.checked)}
            className="rounded border-border"
          />
          Create private GitHub repo now (linnana8888888) — usually leave off and use Publish later
        </label>
        <label className="flex items-center gap-2 text-sm text-text-muted">
          <input
            type="checkbox"
            checked={rosterApproval}
            onChange={(e) => setRosterApproval(e.target.checked)}
            className="rounded border-border"
          />
          Require human approval for agent roster
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-sm text-text-muted hover:text-text">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!name || submitting}
            className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {submitting ? "Creating..." : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
