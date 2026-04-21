import { useState, useEffect } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { getProject, runPipeline, advancePipeline } from "../api/client";
import { useTasks } from "../hooks/useTasks";
import { useAgents } from "../hooks/useAgents";
import { useWebSocket } from "../api/websocket";
import TaskBoard from "../components/tasks/TaskBoard";
import CreateTaskModal from "../components/tasks/CreateTaskModal";
import NeedsAttention from "../components/tasks/NeedsAttention";
import InstanceList from "../components/agents/InstanceList";
import ChannelView from "../components/channels/ChannelView";
import ActivityFeed from "../components/activity/ActivityFeed";
import GatesPanel from "../components/gates/GatesPanel";
import CriteriaPanel from "../components/project/CriteriaPanel";
import DocsBrowser from "../components/docs/DocsBrowser";
import type { Project } from "../types/api";

type Section = "tasks" | "plan" | "docs" | "agents" | "channels";

interface GateBannerEntry {
  task_id: string;
  step_id?: string;
  review_of?: string;
  title?: string;
}

interface SpawnFailedEntry {
  task_id: string;
  agent_type: string;
  error: string;
  failures: number;
  hint?: string;
}

interface RosterPending {
  batch_id: string;
  pipeline: string;
  proposal_count: number;
}

export default function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [section, setSection] = useState<Section>(
    searchParams.get("expanded") ? "plan" : "tasks",
  );
  const [createTaskOpen, setCreateTaskOpen] = useState(false);
  const [gateBanner, setGateBanner] = useState<GateBannerEntry | null>(null);
  const [spawnFailures, setSpawnFailures] = useState<SpawnFailedEntry[]>([]);
  const [relaunchOpen, setRelaunchOpen] = useState(false);
  const [relaunchInput, setRelaunchInput] = useState("");
  const [relaunching, setRelaunching] = useState(false);
  const [relaunchMsg, setRelaunchMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [iterating, setIterating] = useState(false);
  const [rosterPending, setRosterPending] = useState<RosterPending | null>(null);
  const { tasks, create: createTask, refresh: refreshTasks } = useTasks(id);
  const { instances, terminate } = useAgents();
  const expandedId = searchParams.get("expanded") ?? undefined;

  useEffect(() => {
    if (id) getProject(id).then(setProject).catch(() => {});
  }, [id]);

  useWebSocket((event) => {
    if (!id) return;
    const e = event as { type?: string; data?: Record<string, unknown> };
    if (!e.data || e.data.project_id !== id) return;
    if (e.type === "gate_ready") {
      setGateBanner({
        task_id: String(e.data.task_id),
        step_id: e.data.step_id as string | undefined,
        review_of: e.data.review_of as string | undefined,
        title: e.data.title as string | undefined,
      });
      return;
    }
    if (e.type === "roster_proposed") {
      setRosterPending({
        batch_id: String(e.data.batch_id),
        pipeline: String(e.data.pipeline || ""),
        proposal_count: Number(e.data.proposal_count || 0),
      });
      return;
    }
    if (e.type === "pipeline_started") {
      setRosterPending(null);
      return;
    }
    if (e.type === "spawn_failed") {
      setSpawnFailures((prev) => {
        const task_id = String(e.data!.task_id);
        const entry: SpawnFailedEntry = {
          task_id,
          agent_type: String(e.data!.agent_type || "?"),
          error: String(e.data!.error || ""),
          failures: Number(e.data!.failures || 0),
          hint: e.data!.hint as string | undefined,
        };
        return [entry, ...prev.filter((p) => p.task_id !== task_id)].slice(0, 5);
      });
    }
  });

  function openGate(entry: GateBannerEntry) {
    setSection("plan");
    setSearchParams({ expanded: entry.task_id });
    setGateBanner(null);
  }

  async function onRelaunch() {
    if (!id) return;
    setRelaunching(true);
    setRelaunchMsg(null);
    try {
      await runPipeline("phased-producer", id, relaunchInput || project?.goal || "");
      setRelaunchMsg({ kind: "ok", text: "phased-producer launched — tasks queued." });
      setRelaunchInput("");
      setTimeout(refreshTasks, 500);
    } catch (e) {
      setRelaunchMsg({ kind: "err", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setRelaunching(false);
    }
  }

  async function onIterate() {
    if (!id) return;
    setIterating(true);
    setRelaunchMsg(null);
    try {
      const res = await advancePipeline(id, "iterate_artifact") as Record<string, unknown>;
      if (res?.status === "pending_roster_approval") {
        setRosterPending({
          batch_id: String(res.batch_id || ""),
          pipeline: String(res.pipeline || "iterate_artifact"),
          proposal_count: Array.isArray(res.proposals) ? res.proposals.length : 0,
        });
        setRelaunchMsg({ kind: "ok", text: "Roster approval needed — review agent proposals before pipeline starts." });
      } else {
        setRelaunchMsg({ kind: "ok", text: "iterate_artifact launched — playtest → postmortem → propose → implement." });
      }
      setSection("tasks");
      setTimeout(refreshTasks, 500);
    } catch (e) {
      setRelaunchMsg({ kind: "err", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setIterating(false);
    }
  }

  if (!id) return null;

  const projectInstances = instances.filter((i) => i.project_id === id);

  return (
    <div className="space-y-6">
      {/* Breadcrumb + project header */}
      <div>
        <Link to="/" className="text-xs text-text-muted hover:text-accent">
          Dashboard
        </Link>
        <span className="mx-2 text-text-muted">/</span>
        <span className="text-xs font-medium">{project?.name || id}</span>
      </div>

      {project && (
        <div
          className="rounded-2xl border border-border bg-bg-card p-6"
          style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-[28px] font-semibold tight-display">{project.name}</h1>
              <p className="mt-1.5 text-sm text-text-muted">{project.description}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-muted">
                <span className="badge badge-running">{project.tech_stack}</span>
                {project.goal && <span>Goal: {project.goal}</span>}
                {project.require_roster_approval && (
                  <span className="badge badge-assigned">roster approval</span>
                )}
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {project.iterate_enabled ? (
                <button
                  onClick={onIterate}
                  disabled={iterating || !!rosterPending || tasks.some((t) => t.title.includes("[iterate_artifact]") && t.status !== "done")}
                  className="btn-accent"
                  title="Run iterate_artifact: playtest → postmortem → propose → implement"
                >
                  {iterating ? "Launching…" : rosterPending ? "Roster Pending…" : tasks.some((t) => t.title.includes("[iterate_artifact]") && t.status !== "done") ? "Iterating…" : "▶ Iterate"}
                </button>
              ) : null}
              <button
                onClick={() => setRelaunchOpen((v) => !v)}
                className="btn-ghost"
                title="Re-run phased-producer with custom input"
              >
                {relaunchOpen ? "Cancel" : "↻ Relaunch"}
              </button>
            </div>
          </div>

          {relaunchMsg && (
            <div
              className="mt-3 rounded-xl border px-4 py-2.5 text-sm"
              style={
                relaunchMsg.kind === "ok"
                  ? { borderColor: "var(--color-accent)", background: "var(--color-accent-tint)", color: "var(--color-accent-hover)" }
                  : { borderColor: "var(--color-danger)", background: "#fee2e2", color: "#991b1b" }
              }
            >
              {relaunchMsg.text}
            </div>
          )}

          {relaunchOpen && (
            <div className="mt-4 rounded-xl border border-border-strong bg-bg-subtle p-4">
              <p className="mono-label mb-2">Relaunch phased-producer</p>
              <textarea
                rows={2}
                value={relaunchInput}
                onChange={(e) => setRelaunchInput(e.target.value)}
                placeholder={project.goal ? `Leave blank to reuse goal: "${project.goal}"` : "Game concept (fills {input})"}
                className="w-full rounded-2xl border border-border-strong bg-white px-4 py-2 text-sm outline-none placeholder:text-text-subtle focus:border-accent"
              />
              <div className="mt-3 flex items-center gap-2">
                <button onClick={onRelaunch} disabled={relaunching} className="btn-primary">
                  {relaunching ? "Launching…" : "Launch"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <CriteriaPanel projectId={id} />


      {spawnFailures.length > 0 && (
        <div className="space-y-2">
          {spawnFailures.map((f) => (
            <div
              key={f.task_id}
              className="flex items-start justify-between gap-3 rounded-2xl border p-4 text-sm"
              style={{ borderColor: "var(--color-danger)", background: "#fee2e2" }}
            >
              <div className="min-w-0">
                <p className="mono-label" style={{ color: "#991b1b" }}>
                  Task blocked — agent spawn failed
                </p>
                <p className="mt-1 truncate text-xs text-text">
                  <span style={{ fontFamily: "var(--font-mono)" }}>{f.agent_type}</span>
                  <span className="text-text-muted">
                    {" "}· task {f.task_id} · {f.failures} attempts
                  </span>
                </p>
                <p className="mt-1 break-words text-xs text-text-muted">
                  {f.error}
                </p>
                {f.hint && (
                  <p className="mt-1 text-[11px] text-text-muted italic">
                    {f.hint}
                  </p>
                )}
              </div>
              <button
                onClick={() =>
                  setSpawnFailures((prev) => prev.filter((p) => p.task_id !== f.task_id))
                }
                className="btn-ghost shrink-0"
              >
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}

      {rosterPending ? (
        <div
          className="flex items-center justify-between gap-3 rounded-2xl border p-4 text-sm"
          style={{ borderColor: "var(--color-warning)", background: "#fef9c3" }}
        >
          <div>
            <p className="mono-label" style={{ color: "#92400e" }}>
              Roster approval needed
            </p>
            <p className="mt-1 text-xs text-text-muted">
              {rosterPending.proposal_count} agent{rosterPending.proposal_count !== 1 ? "s" : ""} proposed
              for {rosterPending.pipeline}. Review and approve before the pipeline starts.
            </p>
          </div>
          <div className="flex gap-2">
            <Link to={`/governance?batch=${rosterPending.batch_id}`} className="btn-primary">
              Review Roster
            </Link>
            <button onClick={() => setRosterPending(null)} className="btn-ghost">
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {gateBanner ? (
        <div
          className="flex items-center justify-between gap-3 rounded-2xl border p-4 text-sm"
          style={{ borderColor: "var(--color-accent)", background: "var(--color-accent-tint)" }}
        >
          <div>
            <p className="mono-label" style={{ color: "var(--color-accent-hover)" }}>
              Human review needed
            </p>
            <p className="mt-1 text-xs text-text-muted">
              {gateBanner.review_of
                ? `Gate for ${gateBanner.review_of}`
                : gateBanner.title || "Pipeline gate is ready"}
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => openGate(gateBanner)} className="btn-primary">
              Open
            </button>
            <button onClick={() => setGateBanner(null)} className="btn-ghost">
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {/* Section tabs */}
      <div
        className="inline-flex rounded-full border border-border-strong bg-white p-1"
        style={{ boxShadow: "rgba(0,0,0,0.03) 0px 1px 2px" }}
      >
        {(["tasks", "plan", "docs", "agents", "channels"] as Section[]).map((s) => (
          <button
            key={s}
            onClick={() => {
              setSection(s);
              if (s !== "plan" && expandedId) {
                searchParams.delete("expanded");
                setSearchParams(searchParams);
              }
            }}
            className={`rounded-full px-4 py-1.5 text-sm font-medium capitalize transition-colors ${
              section === s
                ? "bg-[#0d0d0d] text-white"
                : "text-text-muted hover:text-text"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {section === "tasks" && (
        <>
          <NeedsAttention tasks={tasks} onRetried={refreshTasks} />
          <TaskBoard
            tasks={tasks}
            onCreate={() => setCreateTaskOpen(true)}
            onRetried={refreshTasks}
          />
          <CreateTaskModal
            open={createTaskOpen}
            projectId={id}
            onClose={() => setCreateTaskOpen(false)}
            onCreate={async (data) => { await createTask(data); }}
          />
        </>
      )}

      {section === "plan" && (
        <GatesPanel projectId={id} initialExpandedId={expandedId} />
      )}

      {section === "docs" && <DocsBrowser projectId={id} />}

      {section === "agents" && (
        <InstanceList instances={projectInstances} onTerminate={terminate} />
      )}

      {section === "channels" && (
        <div className="space-y-6">
          <ActivityFeed />
          <div className="h-[500px]">
            <ChannelView projectId={id} />
          </div>
        </div>
      )}
    </div>
  );
}
