import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import StatsOverview from "../components/stats/StatsOverview";
import ProjectGrid from "../components/projects/ProjectGrid";
import CreateProjectModal from "../components/projects/CreateProjectModal";
import ActivityFeed from "../components/activity/ActivityFeed";
import AgentRoster from "../components/agents/AgentRoster";
import InstanceList from "../components/agents/InstanceList";
import GovernancePanel from "../components/governance/GovernancePanel";
import PipelineLauncher from "../components/pipelines/PipelineLauncher";
import { useProjects } from "../hooks/useProjects";
import { useAgents } from "../hooks/useAgents";

const tabs = ["overview", "agents", "tasks", "governance"] as const;
type Tab = (typeof tabs)[number];

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") as Tab) || "overview";
  const [createOpen, setCreateOpen] = useState(false);
  const { projects, create } = useProjects();
  const { definitions, categories, instances, spawn, terminate } = useAgents();

  const setTab = (t: Tab) => {
    if (t === "overview") setSearchParams({});
    else setSearchParams({ tab: t });
  };

  return (
    <div className="space-y-6">
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border pb-px">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-t-lg px-4 py-2 text-sm font-medium capitalize transition-colors ${
              activeTab === t
                ? "border-b-2 border-accent text-accent"
                : "text-text-muted hover:text-text"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <>
          <StatsOverview />
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ProjectGrid projects={projects} onCreate={() => setCreateOpen(true)} />
            </div>
            <ActivityFeed />
          </div>
          <PipelineLauncher projects={projects} />
        </>
      )}

      {activeTab === "agents" && (
        <>
          <AgentRoster definitions={definitions} categories={categories} onSpawn={spawn} />
          <InstanceList instances={instances} onTerminate={terminate} />
        </>
      )}

      {activeTab === "tasks" && (
        <p className="text-sm text-text-muted">
          Select a project to view its task board.
        </p>
      )}

      {activeTab === "governance" && <GovernancePanel />}

      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={async (data) => { await create(data); }}
      />
    </div>
  );
}
