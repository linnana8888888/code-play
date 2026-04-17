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
import type { Project } from "../types/api";

type Section = "tasks" | "plan" | "agents" | "channels";

interface GateBannerEntry {
  task_id: string;
  step_id?: string;
  review_of?: string;
  title?: string;
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
  const { tasks, create: createTask } = useTasks(id);
  const { instances, terminate } = useAgents();
  const expandedId = searchParams.get("expanded") ?? undefined;

  useEffect(() => {
    if (id) getProject(id).then(setProject).catch(() => {});
  }, [id]);

  useWebSocket((event) => {
    if (!id) return;
    const e = event as { type?: string; data?: Record<string, unknown> };
    if (e.type !== "gate_ready") return;
    if (!e.data || e.data.project_id !== id) return;
    setGateBanner({
      task_id: String(e.data.task_id),
      step_id: e.data.step_id as string | undefined,
      review_of: e.data.review_of as string | undefined,
      title: e.data.title as string | undefined,
    });
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
          <div className="mt-2 flex gap-3 text-xs text-text-muted">
            <span className="badge badge-running">{project.tech_stack}</span>
            {project.goal && <span>Goal: {project.goal}</span>}
          </div>
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
        {(["tasks", "plan", "agents", "channels"] as Section[]).map((s) => (
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
