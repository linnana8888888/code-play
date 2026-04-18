/* Typed REST client for Code PLAY backend */

import type {
  Project,
  ProjectCreate,
  Task,
  TaskCreate,
  AgentDefinition,
  AgentInstance,
  AgentCost,
  Message,
  Skill,
  GovernanceApproval,
  GovernanceLogEntry,
  ToolCatalogEntry,
  Stats,
  PipelineDef,
  ModelOption,
  HumanGate,
} from "../types/api";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined);
  if (!entries.length) return "";
  return "?" + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
}

/* ── Projects ── */
export const getProjects = () => req<Project[]>("/projects");
export const getProject = (id: string) => req<Project>(`/projects/${id}`);
export const createProject = (p: ProjectCreate) =>
  req<Project>("/projects", { method: "POST", body: JSON.stringify(p) });
export const deleteProject = (id: string) =>
  req<{ status: string; project_id: string }>(`/projects/${id}`, { method: "DELETE" });
export const cleanupProjects = (opts: {
  dryRun?: boolean;
  onlyEmpty?: boolean;
  olderThanDays?: number;
  keepIds?: string[];
}) => {
  const params = new URLSearchParams();
  params.set("dry_run", String(opts.dryRun ?? true));
  params.set("only_empty", String(opts.onlyEmpty ?? true));
  if (opts.olderThanDays !== undefined)
    params.set("older_than_days", String(opts.olderThanDays));
  if (opts.keepIds && opts.keepIds.length > 0)
    params.set("keep_ids", opts.keepIds.join(","));
  return req<{
    dry_run: boolean;
    count: number;
    would_delete?: Array<{ id: string; name: string; created_at: string }>;
    deleted?: Array<{ project_id: string }>;
  }>(`/projects/cleanup?${params.toString()}`, { method: "POST" });
};

/* ── Tasks ── */
export const getTasks = (projectId?: string) =>
  req<Task[]>(`/tasks${projectId ? `?project_id=${projectId}` : ""}`);
export const getReadyTasks = (projectId: string) =>
  req<Task[]>(`/projects/${projectId}/tasks/ready`);
export const createTask = (t: TaskCreate) =>
  req<Task>("/tasks", { method: "POST", body: JSON.stringify(t) });
export const patchTask = (id: string, patch: { model_override?: string | null }) =>
  req<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) });

/* ── Models ── */
export const getAvailableModels = () => req<ModelOption[]>("/models/available");

/* ── Gates (human-in-the-loop) ── */
export const getGates = (projectId: string) =>
  req<HumanGate[]>(`/projects/${projectId}/gates`);
export const approveGate = (taskId: string, feedback = "") =>
  req<{ status: string; task_id: string }>(`/gates/${taskId}/approve`, {
    method: "POST",
    body: JSON.stringify({ feedback }),
  });
export const reviseGate = (taskId: string, feedback: string) =>
  req<{ status: string; task_id: string; revision_task_id: string }>(
    `/gates/${taskId}/revise`,
    { method: "POST", body: JSON.stringify({ feedback }) },
  );

/* ── Agents ── */
export const getDefinitions = () => req<AgentDefinition[]>("/agents/definitions");
export const getCategories = () => req<string[]>("/agents/categories");
export const getInstances = () => req<AgentInstance[]>("/agents/instances");
export const spawnAgent = (agentType: string, projectId?: string) =>
  req<AgentInstance>(
    `/agents/spawn${qs({ agent_type: agentType, project_id: projectId })}`,
    { method: "POST" },
  );
export const terminateAgent = (id: string) =>
  req<{ status: string }>(`/agents/${id}/terminate`, { method: "POST" });
export const getAgentCost = (id: string) => req<AgentCost>(`/agents/${id}/cost`);

/* ── Messages ── */
export const getMessages = (projectId: string, channel: string) =>
  req<Message[]>(`/messages${qs({ project_id: projectId, channel })}`);
export const getChannels = (projectId: string) =>
  req<string[]>(`/messages/channels${qs({ project_id: projectId })}`);
export const postMessage = (
  projectId: string,
  channel: string,
  sender: string,
  content: string,
) =>
  req<Message>(`/messages${qs({ project_id: projectId, channel, sender, content })}`, {
    method: "POST",
  });

/* ── Skills ── */
export const getSkills = () => req<Skill[]>("/skills");
export const getSkill = (id: string) => req<Skill>(`/skills/${id}`);
export const approveSkill = (id: string, agentType: string) =>
  req<{ status: string }>(`/skills/${id}/approve${qs({ agent_type: agentType })}`, {
    method: "POST",
  });

/* ── Governance ── */
export const getApprovals = () => req<GovernanceApproval[]>("/governance/approvals");
export const getGovernanceLog = () => req<GovernanceLogEntry[]>("/governance/log");
export const getToolCatalog = () => req<ToolCatalogEntry[]>("/governance/tools");

/* ── Pipelines ── */
export const getPipelines = () =>
  req<PipelineDef[]>("/pipelines");
export const runPipeline = (name: string, projectId: string, inputText = "") =>
  req<{ status: string }>(`/pipelines/${name}/run`, {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, input_text: inputText }),
  });

/* ── Stats ── */
export const getStats = () => req<Stats>("/stats");

/* ── Memory ── */
export const getMemory = (projectId: string, memType: string, key: string) =>
  req<{ content: string }>(`/projects/${projectId}/memory${qs({ mem_type: memType, key })}`);
export const searchMemory = (projectId: string, query: string) =>
  req<Record<string, unknown>[]>(`/projects/${projectId}/memory/search${qs({ query })}`);

/* ── Game preview + asset previews ── */
export const gamePreviewUrl = (projectId: string, key = "game_html_v1") =>
  `${BASE}/projects/${projectId}/game/preview?key=${encodeURIComponent(key)}`;
export type AssetPreview = { path: string; url: string; bytes: number };
export const getAssetPreviews = (projectId: string) =>
  req<AssetPreview[]>(`/projects/${projectId}/assets/previews`);
