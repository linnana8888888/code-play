/* TypeScript types mirroring backend Pydantic models */

export interface Project {
  id: string;
  name: string;
  description: string;
  tech_stack: string;
  goal: string;
  status: string;
  created_at: string;
}

export interface ProjectCreate {
  name: string;
  description: string;
  tech_stack?: string;
  goal?: string;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: "pending" | "assigned" | "running" | "done" | "blocked";
  priority: number;
  assigned_to: string | null;
  parent_task_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface TaskCreate {
  project_id: string;
  title: string;
  description?: string;
  priority?: number;
  parent_task_id?: string;
}

export interface AgentDefinition {
  id: string;
  name: string;
  role: string;
  category: string;
  tools: string[];
  model: string;
}

export interface AgentInstance {
  id: string;
  agent_type: string;
  status: "assigned" | "running" | "idle" | "terminated";
  project_id: string | null;
  task_id: string | null;
  tokens_used: number;
  cost_usd: number;
  budget_max_tokens: number;
  budget_max_usd: number;
  created_at: string;
}

export interface AgentCost {
  instance_id: string;
  tokens_used: number;
  cost_usd: number;
  budget_max_tokens: number;
  budget_max_usd: number;
  breakdown: CostEntry[];
}

export interface CostEntry {
  timestamp: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface Message {
  id: number;
  project_id: string;
  channel: string;
  sender: string;
  content: string;
  timestamp: string;
  mentions: string[];
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  content?: string;
}

export interface GovernanceApproval {
  id: string;
  tool_or_skill: string;
  agent_id: string;
  status: "pending" | "approved" | "denied";
  requested_at: string;
}

export interface GovernanceLogEntry {
  timestamp: string;
  agent_id: string;
  tool: string;
  decision: string;
  detail: string;
}

export interface Pipeline {
  name: string;
  description: string;
  steps: string[];
}

export interface Stats {
  projects: number;
  tasks: Record<string, number>;
  agents: { definitions: number; instances: number; running: number };
  messages: number;
}

export interface WsEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}
