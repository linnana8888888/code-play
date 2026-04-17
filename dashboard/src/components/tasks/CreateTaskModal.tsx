import { useEffect, useState } from "react";
import type { ModelOption, TaskCreate } from "../../types/api";
import { getAvailableModels } from "../../api/client";

interface Props {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onCreate: (data: TaskCreate) => Promise<void>;
}

export default function CreateTaskModal({ open, projectId, onClose, onCreate }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(5);
  const [modelOverride, setModelOverride] = useState("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) getAvailableModels().then(setModels).catch(() => {});
  }, [open]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await onCreate({
      project_id: projectId,
      title,
      description,
      priority,
      model_override: modelOverride || undefined,
    });
    setSubmitting(false);
    setTitle(""); setDescription(""); setModelOverride("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-xl border border-border bg-bg-card p-6 space-y-4"
      >
        <h2 className="text-lg font-semibold">New Task</h2>
        <input
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          placeholder="Task title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        <textarea
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          placeholder="Description"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-text-muted">
          Priority
          <input
            type="number"
            min={1} max={10}
            className="w-16 rounded-lg border border-border bg-bg px-2 py-1 text-sm text-text outline-none"
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
          />
        </label>
        <label className="block text-sm text-text-muted">
          <span className="mb-1 block">Model override</span>
          <select
            value={modelOverride}
            onChange={(e) => setModelOverride(e.target.value)}
            className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          >
            <option value="">agent default</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
                {m.output_per_1m > 0 ? ` — $${m.output_per_1m}/1M out` : " — free"}
              </option>
            ))}
          </select>
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-sm text-text-muted hover:text-text">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!title || submitting}
            className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {submitting ? "Creating..." : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
