import { useState } from "react";
import { useCriteria } from "../../hooks/useCriteria";
import type { CriterionStatus, SuccessCriterion } from "../../types/api";

const STATUS_LABEL: Record<CriterionStatus, string> = {
  pending: "Pending",
  in_progress: "In progress",
  met: "Met",
  failed: "Failed",
};

const STATUS_STYLE: Record<CriterionStatus, string> = {
  pending: "bg-bg-hover text-text-muted border-border",
  in_progress: "bg-accent/15 text-accent border-accent/30",
  met: "bg-success/15 text-success border-success/30",
  failed: "bg-danger/15 text-danger border-danger/30",
};

export default function CriteriaPanel({ projectId }: { projectId: string }) {
  const { criteria, loading, create, update, remove } = useCriteria(projectId);
  const [open, setOpen] = useState(true);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newAcceptance, setNewAcceptance] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<SuccessCriterion>>({});

  async function onAdd() {
    const t = newTitle.trim();
    if (!t) return;
    await create({
      title: t,
      description: newDesc.trim(),
      acceptance_test: newAcceptance.trim(),
      order_index: criteria.length,
    });
    setNewTitle("");
    setNewDesc("");
    setNewAcceptance("");
  }

  function startEdit(c: SuccessCriterion) {
    setEditing(c.id);
    setDraft({
      title: c.title,
      description: c.description,
      acceptance_test: c.acceptance_test,
    });
  }

  async function saveEdit(id: string) {
    await update(id, {
      title: draft.title,
      description: draft.description,
      acceptance_test: draft.acceptance_test,
    });
    setEditing(null);
  }

  async function setStatus(c: SuccessCriterion, status: CriterionStatus) {
    await update(c.id, { status });
  }

  return (
    <div className="rounded-xl border border-border bg-bg-card">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div>
          <h3 className="text-sm font-semibold">Success Criteria</h3>
          <p className="text-xs text-text-muted">
            {criteria.length === 0
              ? "Define measurable outcomes agents should target."
              : `${criteria.filter((c) => c.status === "met").length}/${criteria.length} met`}
          </p>
        </div>
        <span className="text-xs text-text-muted">{open ? "Hide" : "Show"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-border p-4">
          {loading && (
            <p className="text-xs text-text-muted">Loading criteria…</p>
          )}

          {criteria.length === 0 && !loading && (
            <p className="text-xs text-text-muted">
              No criteria yet. Agents will see these in their goal ancestry
              block when you add them.
            </p>
          )}

          <ul className="space-y-2">
            {criteria
              .slice()
              .sort((a, b) => a.order_index - b.order_index)
              .map((c) => (
                <li
                  key={c.id}
                  className="rounded-lg border border-border bg-bg p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      {editing === c.id ? (
                        <div className="space-y-2">
                          <input
                            value={draft.title ?? ""}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, title: e.target.value }))
                            }
                            className="w-full rounded border border-border bg-bg-card px-2 py-1 text-sm"
                            placeholder="Title"
                          />
                          <textarea
                            value={draft.description ?? ""}
                            onChange={(e) =>
                              setDraft((d) => ({
                                ...d,
                                description: e.target.value,
                              }))
                            }
                            className="w-full rounded border border-border bg-bg-card px-2 py-1 text-xs"
                            rows={2}
                            placeholder="Description (optional)"
                          />
                          <textarea
                            value={draft.acceptance_test ?? ""}
                            onChange={(e) =>
                              setDraft((d) => ({
                                ...d,
                                acceptance_test: e.target.value,
                              }))
                            }
                            className="w-full rounded border border-border bg-bg-card px-2 py-1 text-xs"
                            rows={2}
                            placeholder="Acceptance test — how we verify this"
                          />
                        </div>
                      ) : (
                        <>
                          <p className="text-sm font-medium">{c.title}</p>
                          {c.description && (
                            <p className="mt-1 text-xs text-text-muted">
                              {c.description}
                            </p>
                          )}
                          {c.acceptance_test && (
                            <p className="mt-1 text-[11px] italic text-text-muted">
                              ✓ {c.acceptance_test}
                            </p>
                          )}
                        </>
                      )}
                    </div>
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${STATUS_STYLE[c.status]}`}
                    >
                      {STATUS_LABEL[c.status]}
                    </span>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {editing === c.id ? (
                      <>
                        <button
                          onClick={() => saveEdit(c.id)}
                          className="rounded bg-accent px-2 py-0.5 text-xs font-medium text-white"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditing(null)}
                          className="rounded bg-bg-hover px-2 py-0.5 text-xs text-text-muted"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <select
                          value={c.status}
                          onChange={(e) =>
                            setStatus(c, e.target.value as CriterionStatus)
                          }
                          className="rounded border border-border bg-bg-card px-2 py-0.5 text-xs"
                        >
                          <option value="pending">pending</option>
                          <option value="in_progress">in_progress</option>
                          <option value="met">met</option>
                          <option value="failed">failed</option>
                        </select>
                        <button
                          onClick={() => startEdit(c)}
                          className="rounded bg-bg-hover px-2 py-0.5 text-xs text-text-muted hover:text-text"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => remove(c.id)}
                          className="rounded bg-danger/15 px-2 py-0.5 text-xs text-danger hover:bg-danger/25"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </li>
              ))}
          </ul>

          <div className="rounded-lg border border-dashed border-border p-3">
            <p className="mb-2 text-xs font-medium text-text-muted">
              Add criterion
            </p>
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              className="mb-2 w-full rounded border border-border bg-bg px-2 py-1 text-sm"
              placeholder="e.g. 60fps on M1 macbook"
            />
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="mb-2 w-full rounded border border-border bg-bg px-2 py-1 text-xs"
              rows={2}
              placeholder="Description (optional)"
            />
            <textarea
              value={newAcceptance}
              onChange={(e) => setNewAcceptance(e.target.value)}
              className="mb-2 w-full rounded border border-border bg-bg px-2 py-1 text-xs"
              rows={2}
              placeholder="Acceptance test (optional)"
            />
            <button
              onClick={onAdd}
              disabled={!newTitle.trim()}
              className="rounded-lg bg-accent px-3 py-1 text-xs font-semibold text-white disabled:opacity-40"
            >
              Add
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
