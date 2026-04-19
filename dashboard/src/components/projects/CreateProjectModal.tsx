import { useState } from "react";
import type { ProjectCreate } from "../../types/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreate: (data: ProjectCreate, opts: { autoLaunch: boolean }) => Promise<void>;
}

export default function CreateProjectModal({ open, onClose, onCreate }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [techStack, setTechStack] = useState("threejs");
  const [goal, setGoal] = useState("");
  const [createRepo, setCreateRepo] = useState(false);
  const [rosterApproval, setRosterApproval] = useState(true);
  const [autoLaunch, setAutoLaunch] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await onCreate(
      {
        name,
        description,
        tech_stack: techStack,
        goal: goal || undefined,
        create_repo: createRepo,
        require_roster_approval: rosterApproval,
      },
      { autoLaunch },
    );
    setSubmitting(false);
    setName(""); setDescription(""); setGoal("");
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(13,13,13,0.4)", backdropFilter: "blur(4px)" }}
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-3xl border border-border bg-bg-card p-8 space-y-4"
        style={{ boxShadow: "rgba(0,0,0,0.08) 0px 8px 24px" }}
      >
        <h2 className="text-[22px] font-semibold tight-heading">New Project</h2>
        <input
          className="w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm text-text outline-none placeholder:text-text-subtle focus:border-accent"
          placeholder="Project name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <textarea
          className="w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm text-text outline-none placeholder:text-text-subtle focus:border-accent"
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
          className="w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm text-text outline-none placeholder:text-text-subtle focus:border-accent"
          placeholder="Goal (optional)"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-text-muted">
          <input
            type="checkbox"
            checked={autoLaunch}
            onChange={(e) => setAutoLaunch(e.target.checked)}
            className="rounded border-border"
          />
          <span>
            Auto-launch <span className="font-medium text-text">phased-producer</span> pipeline on create
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm text-text-muted">
          <input
            type="checkbox"
            checked={createRepo}
            onChange={(e) => setCreateRepo(e.target.checked)}
            className="rounded border-border"
          />
          Create private GitHub repo now (linnana8888888)
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
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button type="submit" disabled={!name || submitting} className="btn-primary">
            {submitting ? "Creating…" : autoLaunch ? "Create & launch" : "Create project"}
          </button>
        </div>
      </form>
    </div>
  );
}
