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
  Stats,
  PipelineDef,
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

/* ── Tasks ── */
export const getTasks = (projectId?: string) =>
  req<Task[]>(`/tasks${projectId ? `?project_id=${projectId}` : ""}`);
export const getReadyTasks = (projectId: string) =>
  req<Task[]>(`/projects/${projectId}/tasks/ready`);
export const createTask = (t: TaskCreate) =>
  req<Task>("/tasks", { method: "POST", body: JSON.stringify(t) });

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
