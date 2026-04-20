"""Agent Runtime — model-agnostic agentic tool-use loop.

Like Claude Code's internal loop, but for any LLM:
1. Build prompt (system + conversation + tool schemas)
2. Call LLM via router
3. If response has tool_calls → execute each → append results → loop
4. If response has text only → return final answer
5. Enforce max iterations to prevent runaway loops
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from src.models.agents import AgentDefinition, AgentInstance, AgentStatus
from src.models.llm import LLMRequest, LLMResponse, ToolCall, ToolResult
from src.runtime.llm_router import router
from src.runtime.tool_executor import tool_executor
from src.runtime.session_store import session_store
from src.runtime.workspace import workspace_manager
from src.runtime.skill_registry import skill_registry
from src.runtime.path_rules import match_rules as match_path_rules
from src.runtime.artifact_templates import get_template_for_task
from src.orchestrator.agent_registry import registry
from src.orchestrator.task_queue import task_queue
from src.database import get_studio_db

logger = logging.getLogger("code_play.runtime")

MAX_ITERATIONS = 25  # Safety cap on tool-use loops
MAX_CONVERSATION_TOKENS = 50000  # Approximate token budget


class AgentTurn:
    """One step in an agent's execution — either an LLM response or tool results."""
    def __init__(
        self,
        role: str,
        content: str = None,
        tool_calls: list[ToolCall] = None,
        tool_results: list[ToolResult] = None,
        llm_response: LLMResponse = None,
    ):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_results = tool_results or []
        self.llm_response = llm_response
        self.timestamp = datetime.now(timezone.utc)


class AgentRuntime:
    """Execute an agent instance through its full lifecycle."""

    async def run(
        self,
        instance: AgentInstance,
        task_prompt: str,
        context_messages: list[dict] = None,
        session_id: str = None,
    ) -> AsyncIterator[AgentTurn]:
        """Run an agent to completion, yielding each turn for observability.

        Args:
            instance: The AgentInstance to run (from registry.spawn)
            task_prompt: The user/orchestrator message that kicks off work
            context_messages: Optional prior conversation context (e.g. from memory)
            session_id: Optional session ID to resume a previous conversation

        Yields:
            AgentTurn objects for each LLM call and tool execution round
        """
        defn = registry.get_definition(instance.agent_type)
        if not defn:
            raise ValueError(f"No definition for agent type: {instance.agent_type}")

        # Update status
        registry.update_status(instance.id, AgentStatus.RUNNING)
        self._log_event(instance, "started", f"Task: {task_prompt[:100]}")

        # Create isolated workspace if project has files
        if instance.project_id:
            try:
                workspace_manager.create(instance.project_id, instance.id)
            except Exception as e:
                logger.warning(f"[{instance.id}] Workspace creation failed (non-fatal): {e}")

        # Track which path-scoped rule labels have been injected (avoids duplicates)
        self._injected_path_labels: set[str] = set()

        # Resume from saved session or build fresh conversation
        if session_id:
            saved = session_store.load(session_id)
            if saved:
                conversation = saved["conversation"]
                # Append the new task prompt as continuation
                conversation.append({"role": "user", "content": task_prompt})
                instance.tokens_used = saved["tokens_used"]
                self._log_event(instance, "resumed", f"Session: {session_id}")
            else:
                conversation = self._build_initial_conversation(
                    defn, task_prompt, context_messages, instance.project_id, instance.task_id
                )
        else:
            conversation = self._build_initial_conversation(
                defn, task_prompt, context_messages, instance.project_id, instance.task_id
            )

        # Get available tools for this agent
        tool_schemas = self._get_agent_tools(defn)

        iteration = 0
        total_input_tokens = 0
        total_output_tokens = 0

        try:
            while iteration < MAX_ITERATIONS:
                iteration += 1
                logger.info(f"[{instance.id}] Iteration {iteration}/{MAX_ITERATIONS}")

                # Call LLM
                request = LLMRequest(
                    messages=conversation,
                    model=instance.model,
                    tools=tool_schemas if tool_schemas else None,
                    temperature=0.7,
                    max_tokens=16384,
                )

                try:
                    response = await router.complete(request)
                except Exception as e:
                    # Try fallback model
                    if defn.fallback_model and instance.model != defn.fallback_model:
                        logger.warning(
                            f"[{instance.id}] Primary model failed, trying fallback: {e}"
                        )
                        instance.model = defn.fallback_model
                        request.model = defn.fallback_model
                        response = await router.complete(request)
                    else:
                        raise

                total_input_tokens += response.input_tokens
                total_output_tokens += response.output_tokens

                # Log cost for this call
                self._log_cost(instance, response)

                # Update instance running totals
                instance.tokens_used = total_input_tokens + total_output_tokens

                # Budget enforcement — check after each LLM call
                if self._budget_exceeded(instance):
                    registry.update_status(instance.id, AgentStatus.TERMINATED)
                    reason = self._budget_exceeded_reason(instance)
                    self._log_event(instance, "budget_exceeded", reason)
                    logger.warning(f"[{instance.id}] Budget exceeded: {reason}")
                    yield AgentTurn(
                        role="assistant",
                        content=f"[TERMINATED] Budget exceeded: {reason}",
                    )
                    return

                # Yield the LLM response turn
                turn = AgentTurn(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                    llm_response=response,
                )
                yield turn

                # If no tool calls, agent is done
                if not response.tool_calls:
                    break

                # Append assistant message to conversation
                conversation.append(self._response_to_message(response))

                # Execute tool calls
                tool_results = await self._execute_tool_calls(
                    response.tool_calls, instance
                )

                # Yield tool results turn
                results_turn = AgentTurn(
                    role="tool",
                    tool_results=tool_results,
                )
                yield results_turn

                # Append tool results to conversation
                for tc, result in zip(response.tool_calls, tool_results):
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.content,
                    })

                # Mid-loop path-scoped rule injection — scan tool results for
                # new file paths and inject any rule sets not seen yet.
                tool_text = "\n".join(r.content for r in tool_results if r.content)
                new_rules, new_labels = match_path_rules(
                    tool_text, exclude_labels=self._injected_path_labels
                )
                if new_rules:
                    self._injected_path_labels |= new_labels
                    conversation.append({
                        "role": "system",
                        "content": new_rules,
                    })

                # Persist session after each tool iteration
                try:
                    session_id = session_store.save(
                        instance_id=instance.id,
                        conversation=conversation,
                        tokens_used=instance.tokens_used,
                        iteration=iteration,
                        session_id=session_id,
                    )
                except Exception:
                    pass  # Don't let session save failures break the runtime

            # Update instance stats
            instance.tokens_used = total_input_tokens + total_output_tokens
            registry.record_usage(instance.id, instance.tokens_used, instance.cost_usd)
            registry.update_status(instance.id, AgentStatus.COMPLETED)
            self._log_event(
                instance, "completed",
                f"Iterations: {iteration}, tokens: {instance.tokens_used}",
            )

        except Exception as e:
            registry.record_usage(instance.id, total_input_tokens + total_output_tokens, instance.cost_usd)
            registry.update_status(instance.id, AgentStatus.FAILED)
            self._log_event(instance, "failed", str(e))
            raise
        finally:
            # Cleanup workspace (leave for review on completion, force on failure/termination)
            if instance.project_id and instance.status in (AgentStatus.FAILED, AgentStatus.TERMINATED):
                try:
                    workspace_manager.cleanup(instance.project_id, instance.id)
                except Exception:
                    pass

    async def run_to_completion(
        self,
        instance: AgentInstance,
        task_prompt: str,
        context_messages: list[dict] = None,
        session_id: str = None,
    ) -> str:
        """Convenience: run and return just the final text response."""
        final_content = ""
        async for turn in self.run(instance, task_prompt, context_messages, session_id):
            if turn.role == "assistant" and turn.content:
                final_content = turn.content
        return final_content

    # --- Conversation building ---

    def _build_initial_conversation(
        self,
        defn: AgentDefinition,
        task_prompt: str,
        context_messages: list[dict] = None,
        project_id: str = None,
        task_id: str = None,
    ) -> list[dict]:
        """Build the initial messages array for the LLM."""
        messages = []

        # System prompt from agent definition
        system_content = defn.system_prompt

        # Inject goal ancestry chain
        ancestry = self._build_goal_ancestry(project_id, task_id)
        if ancestry:
            system_content += f"\n\n{ancestry}"
        elif project_id:
            system_content += f"\n\n[Project ID: {project_id}]"

        # Inject approved skills. When an agent doesn't declare any, auto-seed
        # from the builtin set (governance + plugin-discovered) so every agent
        # matches the Claude Code CLI surface by default.
        effective_skills = defn.skills or skill_registry.get_builtin_skills()
        if effective_skills:
            skill_content = skill_registry.get_injectable_content(defn.id, effective_skills)
            if skill_content:
                system_content += f"\n\n{skill_content}"

        # Always attach the skill catalog so the agent knows which ids
        # `skill_invoke(...)` accepts even when the full body wasn't injected.
        catalog = skill_registry.catalog_for_prompt()
        if catalog:
            system_content += (
                "\n\n## Available skills (invoke via `skill_invoke(skill_id)`):\n"
                + catalog
            )

        # Inject path-scoped rules based on file references in task + context
        path_rules_text = task_prompt
        if context_messages:
            for msg in context_messages:
                if isinstance(msg.get("content"), str):
                    path_rules_text += "\n" + msg["content"]
        path_rules, initial_labels = match_path_rules(path_rules_text)
        if path_rules:
            system_content += f"\n\n{path_rules}"
        self._injected_path_labels = initial_labels

        # Inject artifact output template if task references a known artifact
        template_content = get_template_for_task(task_prompt)
        if template_content:
            system_content += (
                "\n\n## Output Template\n"
                "Use this template structure for your artifact output. "
                "Fill in the {{placeholders}} with actual values. "
                "You may add sections if needed but preserve all existing sections.\n\n"
                + template_content
            )

        messages.append({"role": "system", "content": system_content})

        # Inject context from prior conversation or memory
        if context_messages:
            messages.extend(context_messages)

        # The actual task
        messages.append({"role": "user", "content": task_prompt})

        return messages

    def _get_agent_tools(self, defn: AgentDefinition) -> list[dict]:
        """Get tool schemas this agent is allowed to use.

        Resolves the `"mcp"` sentinel against the live `mcp_bridge` catalog so
        agents spawned after async MCP discovery completes see every discovered
        plugin tool (figma, playwright, qmd, …). The sentinel is preserved in
        `defn.tools` by `AgentRegistry._expand_tools` precisely because the
        catalog is empty when definitions load.
        """
        if defn.tools:
            resolved = self._resolve_mcp_sentinel(defn.tools)
            return tool_executor.get_tool_schemas(resolved)
        # Default: all builtin tools
        return tool_executor.get_tool_schemas()

    @staticmethod
    def _resolve_mcp_sentinel(tools: list[str]) -> list[str]:
        if "mcp" not in tools:
            return tools
        from src.runtime.mcp_bridge import mcp_bridge
        live = list(mcp_bridge.tools.keys())
        out: list[str] = []
        seen: set[str] = set()
        for t in tools:
            if t == "mcp":
                for name in live:
                    if name not in seen:
                        out.append(name)
                        seen.add(name)
            elif t not in seen:
                out.append(t)
                seen.add(t)
        return out

    def _response_to_message(self, response: LLMResponse) -> dict:
        """Convert LLM response to a conversation message."""
        msg = {"role": "assistant"}
        if response.content:
            msg["content"] = response.content
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
        return msg

    # --- Tool execution ---

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        instance: AgentInstance,
    ) -> list[ToolResult]:
        """Execute a batch of tool calls and return results."""
        results = []
        for tc in tool_calls:
            logger.info(f"[{instance.id}] Tool call: {tc.name}({json.dumps(tc.arguments)[:200]})")

            result = await tool_executor.execute(
                tool_name=tc.name,
                arguments=tc.arguments,
                agent_instance_id=instance.id,
                project_id=instance.project_id,
            )
            result.tool_call_id = tc.id
            results.append(result)

            if result.is_error:
                logger.warning(f"[{instance.id}] Tool error: {result.content[:200]}")

        return results

    # --- Goal ancestry ---

    def _build_goal_ancestry(self, project_id: str = None, task_id: str = None) -> str:
        """Build a goal ancestry chain for agent context.

        Structure:
          Studio Goal
          Project: name
          Project Goal: prose summary
          Success Criteria:
            • [status] title
            ...
          Parent Task: ...
          Task: ... (satisfies → criterion title)
        """
        if not project_id:
            return ""

        lines = ["[Goal Ancestry]", "Studio Goal: Build innovative web/3D games"]

        criterion_title_by_id: dict[str, str] = {}
        try:
            with get_studio_db() as db:
                row = db.execute(
                    "SELECT name, goal FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if row:
                    project_name = row["name"]
                    project_goal = row["goal"] or row["name"]
                    lines.append(f"Project: {project_name}")
                    lines.append(f"Project Goal: {project_goal}")

                criteria = db.execute(
                    """SELECT id, title, status FROM success_criteria
                       WHERE project_id = ? ORDER BY order_index, created_at""",
                    (project_id,),
                ).fetchall()
            if criteria:
                lines.append("Success Criteria:")
                for c in criteria:
                    criterion_title_by_id[c["id"]] = c["title"]
                    lines.append(f"  • [{c['status']}] {c['title']}")
        except Exception:
            lines.append(f"Project ID: {project_id}")

        # Walk task hierarchy
        if task_id:
            task = task_queue.get(task_id)
            if task:
                if task.parent_task_id:
                    parent = task_queue.get(task.parent_task_id)
                    if parent:
                        lines.append(f"Parent Task: {parent.title}")
                crit_label = ""
                criterion_id = getattr(task, "criterion_id", None)
                if criterion_id and criterion_id in criterion_title_by_id:
                    crit_label = f"  (satisfies → {criterion_title_by_id[criterion_id]})"
                lines.append(f"Task: {task.title} — {task.description}{crit_label}")

        return "\n".join(lines)

    # --- Budget enforcement ---

    def _budget_exceeded(self, instance: AgentInstance) -> bool:
        """Check if agent has exceeded its token or USD budget."""
        if instance.budget_max_tokens > 0 and instance.tokens_used >= instance.budget_max_tokens:
            return True
        if instance.budget_max_usd > 0 and instance.cost_usd >= instance.budget_max_usd:
            return True
        return False

    def _budget_exceeded_reason(self, instance: AgentInstance) -> str:
        """Return a human-readable reason for budget termination."""
        parts = []
        if instance.budget_max_tokens > 0 and instance.tokens_used >= instance.budget_max_tokens:
            parts.append(f"tokens {instance.tokens_used}/{instance.budget_max_tokens}")
        if instance.budget_max_usd > 0 and instance.cost_usd >= instance.budget_max_usd:
            parts.append(f"cost ${instance.cost_usd:.4f}/${instance.budget_max_usd:.4f}")
        return ", ".join(parts) or "unknown"

    # --- Observability ---

    def _log_event(self, instance: AgentInstance, event: str, detail: str = ""):
        """Log an agent lifecycle event to the database."""
        try:
            with get_studio_db() as db:
                db.execute(
                    """INSERT INTO governance_log (agent_instance_id, tool_name, params, decision, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (instance.id, f"lifecycle:{event}", "{}", event, detail[:500]),
                )
        except Exception:
            pass  # Don't let logging failures break the runtime

    def _log_cost(self, instance: AgentInstance, response: LLMResponse):
        """Log token usage and cost."""
        try:
            with get_studio_db() as db:
                db.execute(
                    """INSERT INTO cost_log
                       (agent_instance_id, project_id, provider, model, input_tokens, output_tokens, cost_usd)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        instance.id,
                        instance.project_id,
                        response.provider.value,
                        response.model,
                        response.input_tokens,
                        response.output_tokens,
                        response.cost_usd,
                    ),
                )
        except Exception:
            pass


# Singleton
agent_runtime = AgentRuntime()
