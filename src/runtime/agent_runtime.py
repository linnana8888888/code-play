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
from src.orchestrator.agent_registry import registry
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
    ) -> AsyncIterator[AgentTurn]:
        """Run an agent to completion, yielding each turn for observability.

        Args:
            instance: The AgentInstance to run (from registry.spawn)
            task_prompt: The user/orchestrator message that kicks off work
            context_messages: Optional prior conversation context (e.g. from memory)

        Yields:
            AgentTurn objects for each LLM call and tool execution round
        """
        defn = registry.get_definition(instance.agent_type)
        if not defn:
            raise ValueError(f"No definition for agent type: {instance.agent_type}")

        # Update status
        registry.update_status(instance.id, AgentStatus.RUNNING)
        self._log_event(instance, "started", f"Task: {task_prompt[:100]}")

        # Build initial conversation
        conversation = self._build_initial_conversation(
            defn, task_prompt, context_messages, instance.project_id
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
                    max_tokens=4096,
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

            # Update instance stats
            instance.tokens_used = total_input_tokens + total_output_tokens
            registry.update_status(instance.id, AgentStatus.COMPLETED)
            self._log_event(
                instance, "completed",
                f"Iterations: {iteration}, tokens: {instance.tokens_used}",
            )

        except Exception as e:
            registry.update_status(instance.id, AgentStatus.FAILED)
            self._log_event(instance, "failed", str(e))
            raise

    async def run_to_completion(
        self,
        instance: AgentInstance,
        task_prompt: str,
        context_messages: list[dict] = None,
    ) -> str:
        """Convenience: run and return just the final text response."""
        final_content = ""
        async for turn in self.run(instance, task_prompt, context_messages):
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
    ) -> list[dict]:
        """Build the initial messages array for the LLM."""
        messages = []

        # System prompt from agent definition
        system_content = defn.system_prompt
        if project_id:
            system_content += f"\n\n[Project ID: {project_id}]"

        messages.append({"role": "system", "content": system_content})

        # Inject context from prior conversation or memory
        if context_messages:
            messages.extend(context_messages)

        # The actual task
        messages.append({"role": "user", "content": task_prompt})

        return messages

    def _get_agent_tools(self, defn: AgentDefinition) -> list[dict]:
        """Get tool schemas this agent is allowed to use."""
        if defn.tools:
            return tool_executor.get_tool_schemas(defn.tools)
        # Default: all builtin tools
        return tool_executor.get_tool_schemas()

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
