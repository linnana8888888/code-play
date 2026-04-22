/* TypeScript types mirroring backend Pydantic models */

export interface Project {
  id: string;
  name: string;
  description: string;
  tech_stack: string;
  goal: string;
  status: string;
  repo_url?: string | null;
  repo_name?: string | null;
  require_roster_approval?: boolean;
  iterate_enabled?: boolean | number;
  auto_synthesis?: boolean | number;
  created_at: string;
}

export interface ProjectCreate {
  name: string;
  description: string;
  tech_stack?: string;
  goal?: string;
  create_repo?: boolean;
  require_roster_approval?: boolean;
  game_slug?: string;
  pipeline?: string;
}

export interface GameSource {
  kind: string;
  repo?: string | null;
  path?: string | null;
}

export interface GameVersion {
  label: string;
  ref: string;
  status: string;
  branch?: string | null;
  entry?: string | null;
  notes?: string;
}

export interface GameEntry {
  slug: string;
  title: string;
  status: string;
  source: GameSource;
  versions: GameVersion[];
}

export type FailureCategory =
  | "budget_exhausted"
  | "transient"
  | "permanent"
  | "spawn";

export interface TaskResult {
  summary?: string;
  error?: string;
  failure_category?: FailureCategory;
  stall_reason?: string;
  stall_hint?: string;
  tokens_used?: number;
  prev_cap?: number;
  suggested_cap?: number;
  spawn_failures?: number;
  spawn_errors?: string[];
  agent_instance_id?: string;
  retry_history?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: "pending" | "assigned" | "running" | "blocked" | "completed" | "failed";
  priority: number;
  assigned_to: string | null;
  parent_task_id: string | null;
  assignee_type?: string | null;
  model_override?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  result?: TaskResult | null;
  depends_on?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface TaskCreate {
  project_id: string;
  title: string;
  description?: string;
  priority?: number;
  parent_task_id?: string;
  assignee_type?: string;
  model_override?: string;
}

export interface HumanGate {
  task_id: string;
  title: string;
  ready: boolean;
  created_at: string | null;
  pipeline: string;
  pipeline_label: string;
  step_id: string;
  review_of: string | null;
  review_of_agent: string | null;
  prompt: string;
  preceding_result: Record<string, unknown> | null;
  cycle_n: number | null;
  iteration_tag: string | null;
  upstream_blocked?: boolean;
  upstream_blocked_ids?: string[];
}

export interface ModelOption {
  id: string;
  label: string;
  provider: string;
  input_per_1m: number;
  output_per_1m: number;
  notes?: string;
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

export interface ToolCatalogEntry {
  name: string;
  tier: "builtin" | "pre_approved" | "restricted" | "blocked" | "unconfigured";
  description: string;
  has_handler: boolean;
  parameters: Record<string, unknown>;
  agents: string[];
  source?: string;          // "native" | "user" | plugin id (e.g. "figma@claude-plugins-official")
  mcp_server?: string;      // set only for MCP-bridged tools
}

export interface Pipeline {
  name: string;
  description: string;
  steps: string[];
}

export interface PipelineStep {
  id: string;
  agent?: string;
  type?: string;
}
export interface PipelineDef {
  id: string;
  name: string;
  description: string;
  steps: PipelineStep[];
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

export interface AgentActivity {
  instance_id: string;
  agent_type: string;
  activity: "thinking" | "tool_use" | "completed" | "failed";
  tool?: string;
  detail?: string;
  elapsed_ms: number;
  task_id?: string;
}

export interface ActiveWorker {
  task_id: string;
  instance_id: string;
  agent_type: string;
  model: string;
  started_at: string;
  elapsed_ms: number;
}

/* ── Success criteria ── */
export type CriterionStatus = "pending" | "in_progress" | "met" | "failed";

export interface SuccessCriterion {
  id: string;
  project_id: string;
  title: string;
  description: string;
  acceptance_test: string;
  status: CriterionStatus;
  order_index: number;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CriterionCreate {
  title: string;
  description?: string;
  acceptance_test?: string;
  order_index?: number;
}

export interface CriterionUpdate {
  title?: string;
  description?: string;
  acceptance_test?: string;
  status?: CriterionStatus;
  order_index?: number;
}

/* ── Documents ── */
export type DocumentCategory =
  | "design"
  | "architecture"
  | "testing"
  | "analytics"
  | "notes";

export interface DocumentMeta {
  id: string;
  project_id: string;
  category: string;
  slug: string;
  title: string;
  current_version: number;
  status: string;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DocumentRead extends DocumentMeta {
  version: number;
  content: string;
  change_summary: string;
  revision_created_at?: string | null;
}

export interface DocumentRevisionRow {
  version: number;
  change_summary: string;
  created_by?: string | null;
  created_at?: string | null;
}

export interface DocumentCreate {
  category: DocumentCategory;
  slug: string;
  title: string;
  content: string;
  change_summary?: string;
}

export interface DocumentRevise {
  content: string;
  change_summary?: string;
  title?: string;
}

/* ── Budget gate ── */
export type BudgetMode = "parallel" | "extend_cap" | "drop_ideas";

export interface ImplementationPlanIdea {
  id: string;
  title?: string;
  files_touched?: string[];
  est_tokens?: number;
  complexity?: string;
  conflicts_with?: string[];
}

export interface ImplementationPlanSplit {
  engineer_id: string;
  idea_ids: string[];
  est_tokens?: number;
  primary_files?: string[];
}

export interface ImplementationPlanConflict {
  idea_ids: string[];
  file?: string;
  line_region?: string;
  note?: string;
}

export interface ImplementationPlan {
  cycle_n_plus_1?: number;
  ideas?: ImplementationPlanIdea[];
  total_tokens_single?: number;
  total_tokens_parallel?: number;
  lead_coordinator_tokens?: number;
  recommended_split?: ImplementationPlanSplit[];
  conflicts?: ImplementationPlanConflict[];
  recommendation?: BudgetMode;
  recommendation_reason?: string;
}

export interface BudgetDecisionPayload {
  mode: BudgetMode;
  extended_cap?: number;
  kept_ids?: string[];
  split?: ImplementationPlanSplit[];
  reason?: string;
}

/* ── Agent proposals (roster approval) ── */
export type ProposalPhase = "kickoff" | "in_flight";
export type ProposalStatus = "pending" | "approved" | "rejected" | "spawned";

export interface AgentProposal {
  id: string;
  project_id: string;
  batch_id: string;
  agent_type: string;
  rationale: string;
  proposer: string;
  phase: ProposalPhase;
  status: ProposalStatus;
  task_id?: string | null;
  model_override?: string | null;
  decided_by?: string | null;
  decided_at?: string | null;
  spawned_instance_id?: string | null;
  created_at?: string | null;
}
