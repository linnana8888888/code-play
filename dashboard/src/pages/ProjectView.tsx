import { useState, useEffect } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { getProject } from "../api/client";
import { useTasks } from "../hooks/useTasks";
import { useAgents } from "../hooks/useAgents";
import { useWebSocket } from "../api/websocket";
import TaskBoard from "../components/tasks/TaskBoard";
import CreateTaskModal from "../components/tasks/CreateTaskModal";
import InstanceList from "../components/agents/InstanceList";
import ChannelView from "../components/channels/ChannelView";
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
  const { tasks, create: createTask } = useTasks(id);
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
        <div className="rounded-xl border border-border bg-bg-card p-4">
          <h1 className="text-xl font-semibold">{project.name}</h1>
          <p className="mt-1 text-sm text-text-muted">{project.description}</p>
          <div className="mt-2 flex flex-wrap gap-3 text-xs text-text-muted">
            <span className="badge badge-running">{project.tech_stack}</span>
            {project.goal && <span>Goal: {project.goal}</span>}
            {project.require_roster_approval && (
              <span className="rounded border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                roster approval required
              </span>
            )}
          </div>
        </div>
      )}

      <CriteriaPanel projectId={id} />


      {spawnFailures.length > 0 && (
        <div className="space-y-2">
          {spawnFailures.map((f) => (
            <div
              key={f.task_id}
              className="flex items-start justify-between gap-3 rounded-xl border border-red-500/60 bg-red-500/10 p-3 text-sm"
            >
              <div className="min-w-0">
                <p className="font-semibold text-red-400">
                  Task blocked — agent spawn failed
                </p>
                <p className="mt-0.5 truncate text-xs text-text">
                  <span className="font-mono">{f.agent_type}</span>
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
                className="shrink-0 rounded-lg bg-bg-hover px-3 py-1.5 text-xs text-text-muted hover:text-text"
              >
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}

      {gateBanner ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-accent/60 bg-accent/10 p-3 text-sm">
          <div>
            <p className="font-medium text-accent">Human review needed</p>
            <p className="text-xs text-text-muted">
              {gateBanner.review_of
                ? `Gate for ${gateBanner.review_of}`
                : gateBanner.title || "Pipeline gate is ready"}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => openGate(gateBanner)}
              className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90"
            >
              Open
            </button>
            <button
              onClick={() => setGateBanner(null)}
              className="rounded-lg bg-bg-hover px-3 py-1.5 text-xs text-text-muted hover:text-text"
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {/* Section tabs */}
      <div className="flex gap-1 border-b border-border pb-px">
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
            className={`rounded-t-lg px-4 py-2 text-sm font-medium capitalize transition-colors ${
              section === s
                ? "border-b-2 border-accent text-accent"
                : "text-text-muted hover:text-text"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {section === "tasks" && (
        <>
          <TaskBoard tasks={tasks} onCreate={() => setCreateTaskOpen(true)} />
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
        <div className="h-[500px]">
          <ChannelView projectId={id} />
        </div>
      )}
    </div>
  );
}
