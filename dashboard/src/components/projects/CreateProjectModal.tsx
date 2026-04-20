import { useEffect, useState } from "react";
import type { ProjectCreate, GameEntry } from "../../types/api";
import { getGames } from "../../api/client";

type Mode = "new" | "iterate";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreate: (data: ProjectCreate, opts: { autoLaunch: boolean }) => Promise<void>;
}

export default function CreateProjectModal({ open, onClose, onCreate }: Props) {
  const [mode, setMode] = useState<Mode>("new");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [techStack, setTechStack] = useState("threejs");
  const [goal, setGoal] = useState("");
  const [createRepo, setCreateRepo] = useState(false);
  const [rosterApproval, setRosterApproval] = useState(true);
  const [autoLaunch, setAutoLaunch] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  // Iterate mode state
  const [games, setGames] = useState<GameEntry[]>([]);
  const [selectedSlug, setSelectedSlug] = useState("");
  const [gamesLoading, setGamesLoading] = useState(false);

  useEffect(() => {
    if (open && mode === "iterate" && games.length === 0) {
      setGamesLoading(true);
      getGames()
        .then((g) => {
          setGames(g.filter((x) => x.status !== "archived"));
          if (g.length > 0 && !selectedSlug) setSelectedSlug(g[0].slug);
        })
        .catch(() => {})
        .finally(() => setGamesLoading(false));
    }
  }, [open, mode]);

  if (!open) return null;

  const selectedGame = games.find((g) => g.slug === selectedSlug);
  const activeVersion = selectedGame
    ? [...selectedGame.versions].reverse().find((v) =>
        ["active", "shipped", "qa-passing"].includes(v.status),
      ) ?? selectedGame.versions[selectedGame.versions.length - 1]
    : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);

    const payload: ProjectCreate =
      mode === "iterate" && selectedSlug
        ? {
            name: name || selectedGame?.title || selectedSlug,
            description:
              description || `Iterate on ${selectedGame?.title ?? selectedSlug}`,
            game_slug: selectedSlug,
            pipeline: "iterate_artifact",
            require_roster_approval: rosterApproval,
          }
        : {
            name,
            description,
            tech_stack: techStack,
            goal: goal || undefined,
            create_repo: createRepo,
            require_roster_approval: rosterApproval,
          };

    await onCreate(payload, { autoLaunch });
    setSubmitting(false);
    setName("");
    setDescription("");
    setGoal("");
    setSelectedSlug("");
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

        {/* Mode toggle */}
        <div className="flex rounded-xl border border-border overflow-hidden text-sm">
          <button
            type="button"
            onClick={() => setMode("new")}
            className={`flex-1 px-4 py-2 transition-colors ${mode === "new" ? "bg-accent text-white" : "bg-bg text-text-muted hover:bg-bg-hover"}`}
          >
            New game
          </button>
          <button
            type="button"
            onClick={() => setMode("iterate")}
            className={`flex-1 px-4 py-2 transition-colors ${mode === "iterate" ? "bg-accent text-white" : "bg-bg text-text-muted hover:bg-bg-hover"}`}
          >
            Iterate existing
          </button>
        </div>

        {mode === "iterate" ? (
          <>
            {/* Game selector */}
            {gamesLoading ? (
              <p className="text-sm text-text-muted">Loading games…</p>
            ) : games.length === 0 ? (
              <p className="text-sm text-text-muted">
                No games found in <code>games/*.yaml</code>
              </p>
            ) : (
              <select
                className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none"
                value={selectedSlug}
                onChange={(e) => {
                  setSelectedSlug(e.target.value);
                  const g = games.find((x) => x.slug === e.target.value);
                  if (g && !name) setName(g.title);
                }}
              >
                {games.map((g) => (
                  <option key={g.slug} value={g.slug}>
                    {g.title} ({g.slug})
                  </option>
                ))}
              </select>
            )}

            {/* Version info */}
            {activeVersion && (
              <div className="rounded-xl border border-border bg-bg px-4 py-3 text-xs text-text-muted space-y-1">
                <div>
                  <span className="font-medium text-text">
                    {activeVersion.label}
                  </span>{" "}
                  · {activeVersion.status} · ref{" "}
                  <code className="text-accent">{activeVersion.ref.slice(0, 7)}</code>
                </div>
                {activeVersion.notes && (
                  <div className="line-clamp-2">{activeVersion.notes}</div>
                )}
                {selectedGame?.source.repo && (
                  <div className="truncate">
                    {selectedGame.source.repo}
                  </div>
                )}
              </div>
            )}

            <input
              className="w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm text-text outline-none placeholder:text-text-subtle focus:border-accent"
              placeholder="Project name (defaults to game title)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <textarea
              className="w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm text-text outline-none placeholder:text-text-subtle focus:border-accent"
              placeholder="Description (optional)"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </>
        ) : (
          <>
            {/* New game mode — existing fields */}
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
                checked={createRepo}
                onChange={(e) => setCreateRepo(e.target.checked)}
                className="rounded border-border"
              />
              Create private GitHub repo now (linnana8888888)
            </label>
          </>
        )}

        {/* Shared controls */}
        <label className="flex items-center gap-2 text-sm text-text-muted">
          <input
            type="checkbox"
            checked={autoLaunch}
            onChange={(e) => setAutoLaunch(e.target.checked)}
            className="rounded border-border"
          />
          <span>
            Auto-launch{" "}
            <span className="font-medium text-text">
              {mode === "iterate" ? "iterate_artifact" : "phased-producer"}
            </span>{" "}
            pipeline on create
          </span>
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
          <button
            type="submit"
            disabled={
              submitting ||
              (mode === "new" && !name) ||
              (mode === "iterate" && !selectedSlug)
            }
            className="btn-primary"
          >
            {submitting
              ? "Creating…"
              : mode === "iterate"
                ? autoLaunch
                  ? "Create & iterate"
                  : "Create project"
                : autoLaunch
                  ? "Create & launch"
                  : "Create project"}
          </button>
        </div>
      </form>
    </div>
  );
}
