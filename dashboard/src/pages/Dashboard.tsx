import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import StatsOverview from "../components/stats/StatsOverview";
import ProjectGrid from "../components/projects/ProjectGrid";
import CreateProjectModal from "../components/projects/CreateProjectModal";
import ActivityFeed from "../components/activity/ActivityFeed";
import AgentRoster from "../components/agents/AgentRoster";
import InstanceList from "../components/agents/InstanceList";
import GovernancePanel from "../components/governance/GovernancePanel";
import TaskBoard from "../components/tasks/TaskBoard";
import CreateTaskModal from "../components/tasks/CreateTaskModal";
import NeedsAttention from "../components/tasks/NeedsAttention";
import { useProjects } from "../hooks/useProjects";
import { useAgents } from "../hooks/useAgents";
import { useTasks } from "../hooks/useTasks";
import { runPipeline } from "../api/client";

const tabs = ["overview", "agents", "tasks", "governance"] as const;
type Tab = (typeof tabs)[number];

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") as Tab) || "overview";
  const [createOpen, setCreateOpen] = useState(false);
  const [spawnProjectId, setSpawnProjectId] = useState<string>("");
  const [taskFilter, setTaskFilter] = useState<string>("");
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const { projects, create, remove, cleanup, previewCleanup } = useProjects();
  const { definitions, categories, instances, spawn, terminate } = useAgents();
  const { tasks, create: createNewTask, refresh: refreshTasks } = useTasks(taskFilter || undefined);

  const setTab = (t: Tab) => {
    if (t === "overview") setSearchParams({});
    else setSearchParams({ tab: t });
  };

  return (
    <div className="mx-auto max-w-[1200px] space-y-8">
      {/* Tab bar — pill segmented control */}
      <div className="inline-flex gap-1 rounded-full border border-border-strong bg-white p-1">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-full px-4 py-1.5 text-[13px] font-medium capitalize transition-colors ${
              activeTab === t
                ? "bg-[#0d0d0d] text-white"
                : "text-text-muted hover:text-text"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <>
          <NeedsAttention tasks={tasks} onRetried={refreshTasks} />
          <StatsOverview />
          <ProjectGrid
            projects={projects}
            onCreate={() => setCreateOpen(true)}
            onDelete={remove}
            onCleanup={cleanup}
            onPreviewCleanup={previewCleanup}
          />
          <ActivityFeed />
        </>
      )}

      {activeTab === "agents" && (
        <>
          <div className="flex items-center gap-3 rounded-xl border border-border bg-bg-card p-3">
            <label className="text-sm text-text-muted">Spawn for project:</label>
            <select
              value={spawnProjectId}
              onChange={(e) => setSpawnProjectId(e.target.value)}
              className="rounded-lg border border-border bg-bg px-3 py-1.5 text-sm"
            >
              <option value="">— Studio pool (unattached) —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            {!spawnProjectId && (
              <span className="text-xs text-text-muted">
                Tip: pick a project so the agent has a goal and workspace.
              </span>
            )}
          </div>
          <AgentRoster
            definitions={definitions}
            categories={categories}
            onSpawn={(t) => spawn(t, spawnProjectId || undefined)}
          />
          <InstanceList instances={instances} onTerminate={terminate} />
        </>
      )}

      {activeTab === "tasks" && (
        <>
          <div className="flex items-center gap-3 rounded-xl border border-border bg-bg-card p-3">
            <label className="text-sm text-text-muted">Project:</label>
            <select
              value={taskFilter}
              onChange={(e) => setTaskFilter(e.target.value)}
              className="rounded-lg border border-border bg-bg px-3 py-1.5 text-sm"
            >
              <option value="">— All projects —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <span className="ml-auto text-xs text-text-muted">
              {tasks.length} task{tasks.length === 1 ? "" : "s"}
            </span>
          </div>
          <NeedsAttention tasks={tasks} onRetried={refreshTasks} />
          <TaskBoard
            tasks={tasks}
            onCreate={() => setNewTaskOpen(true)}
            onRetried={refreshTasks}
          />
          <CreateTaskModal
            open={newTaskOpen}
            projectId={taskFilter || (projects[0]?.id ?? "")}
            onClose={() => setNewTaskOpen(false)}
            onCreate={async (data) => { await createNewTask(data); }}
          />
        </>
      )}

      {activeTab === "governance" && <GovernancePanel />}

      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={async (data, opts) => {
          const p = await create(data);
          if (opts.autoLaunch) {
            try {
              await runPipeline("phased-producer", p.id, data.goal ?? data.description ?? "");
            } catch (e) {
              console.error("auto-launch phased-producer failed", e);
              alert(`Project created, but pipeline launch failed: ${e instanceof Error ? e.message : e}`);
            }
          }
        }}
      />
    </div>
  );
}
