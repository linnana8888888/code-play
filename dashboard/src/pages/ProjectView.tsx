import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { getProject } from "../api/client";
import { useTasks } from "../hooks/useTasks";
import { useAgents } from "../hooks/useAgents";
import TaskBoard from "../components/tasks/TaskBoard";
import CreateTaskModal from "../components/tasks/CreateTaskModal";
import InstanceList from "../components/agents/InstanceList";
import ChannelView from "../components/channels/ChannelView";
import type { Project } from "../types/api";

type Section = "tasks" | "agents" | "channels";

export default function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [section, setSection] = useState<Section>("tasks");
  const [createTaskOpen, setCreateTaskOpen] = useState(false);
  const { tasks, create: createTask } = useTasks(id);
  const { instances, terminate } = useAgents();

  useEffect(() => {
    if (id) getProject(id).then(setProject).catch(() => {});
  }, [id]);

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

      {/* Section tabs */}
      <div className="flex gap-1 border-b border-border pb-px">
        {(["tasks", "agents", "channels"] as Section[]).map((s) => (
          <button
            key={s}
            onClick={() => setSection(s)}
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
