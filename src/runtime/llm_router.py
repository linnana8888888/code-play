"""LLM Router — multi-provider routing with fallback chains."""
from __future__ import annotations

import asyncio
import json
import logging
import httpx
from src.models.llm import LLMRequest, LLMResponse, ToolCall, Provider
from src.settings import settings

_log = logging.getLogger(__name__)

# LEGO proxy 503s on bursts of large-payload calls even while health-probes stay
# green. Retry 502/503/504/429 with exponential backoff before giving up to the
# fallback_model path.
_RETRY_STATUS = {429, 502, 503, 504}
_RETRY_DELAYS = (1.0, 2.0, 4.0)

# If an agent's accumulated context (input tokens) exceeds this threshold,
# log a warning so operators know summarisation may be needed.
# Configurable via MAX_CONTEXT_TOKENS_BEFORE_SUMMARIZE env var (default 8000).
import os as _os
try:
    max_context_tokens_before_summarize: int = int(
        _os.environ.get("MAX_CONTEXT_TOKENS_BEFORE_SUMMARIZE", "8000")
    )
except (ValueError, TypeError):
    max_context_tokens_before_summarize = 8000


class UpstreamTimeoutError(RuntimeError):
    """Raised when all retry attempts for a 504/502 upstream error are exhausted.

    Callers (agent_runtime / _run_agent_task) catch this to mark the task
    `blocked` with failure_category="upstream_timeout" rather than "failed",
    so it can be retried cleanly once the upstream recovers.
    """
    pass


class LLMRouter:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0))
        self._provider_health: dict[str, bool] = {
            "openrouter": bool(settings.openrouter_api_key),
            "omlx": True,
            "anthropic": bool(settings.anthropic_api_key or settings.anthropic_auth_token),
            "openai": bool(settings.anthropic_auth_token),  # LEGO proxy reuses this token
        }

    async def close(self):
        await self._client.aclose()

    async def _post_with_retry(
        self, url: str, *, json: dict, headers: dict, provider: str
    ) -> httpx.Response:
        """POST with exponential backoff on transient upstream failures.

        Retries on 429/502/503/504 and httpx transport errors. After the last
        attempt the final response (or exception) is returned / raised so the
        caller's fallback_model path can kick in.
        """
        last_exc: Exception | None = None
        last_status: int | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, 0.0)):
            try:
                resp = await self._client.post(url, json=json, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                if delay > 0:
                    _log.warning(
                        "%s transport error (%s), retrying in %.1fs (attempt %d)",
                        provider, type(e).__name__, delay, attempt + 1,
                    )
                    await asyncio.sleep(delay)
                    continue
                # Final transport error — raise as UpstreamTimeoutError so the
                # task runner can mark it blocked/retryable rather than failed.
                raise UpstreamTimeoutError(
                    f"{provider} transport error after {len(_RETRY_DELAYS)} retries: {e}"
                ) from e
            if resp.status_code in _RETRY_STATUS and delay > 0:
                last_status = resp.status_code
                _log.warning(
                    "%s upstream %d, retrying in %.1fs (attempt %d)",
                    provider, resp.status_code, delay, attempt + 1,
                )
                await asyncio.sleep(delay)
                continue
            return resp
        if last_exc:
            raise UpstreamTimeoutError(
                f"{provider} transport error after {len(_RETRY_DELAYS)} retries: {last_exc}"
            ) from last_exc
        # Exhausted retries on a 5xx status code.
        if last_status in (502, 503, 504):
            raise UpstreamTimeoutError(
                f"{provider} upstream {last_status} after {len(_RETRY_DELAYS)} retries"
            )
        return resp  # exhausted retries on 429 or other — let caller raise_for_status

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route an LLM request to the appropriate provider."""
        provider = self._resolve_provider(request.model)
        model_id = self._strip_provider_prefix(request.model)

        # Warn when the conversation context is large enough that summarisation
        # may be needed to avoid context-window / cost issues.
        if request.messages:
            # Rough token estimate: ~4 chars per token for the serialised messages.
            import json as _json_mod
            try:
                approx_chars = sum(
                    len(m.get("content") or "") if isinstance(m.get("content"), str)
                    else len(_json_mod.dumps(m.get("content") or ""))
                    for m in request.messages
                )
                approx_tokens = approx_chars // 4
                if approx_tokens > max_context_tokens_before_summarize:
                    _log.warning(
                        "Context size ~%d tokens exceeds max_context_tokens_before_summarize=%d "
                        "for model %s — consider summarising the conversation.",
                        approx_tokens, max_context_tokens_before_summarize, request.model,
                    )
            except Exception:
                pass  # estimation failure is non-fatal

        try:
            if provider == Provider.OPENROUTER:
                return await self._call_openrouter(model_id, request)
            elif provider == Provider.OMLX:
                return await self._call_omlx(model_id, request)
            elif provider == Provider.ANTHROPIC:
                return await self._call_anthropic(model_id, request)
            elif provider == Provider.OPENAI:
                return await self._call_openai(model_id, request)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except UpstreamTimeoutError:
            # Don't mark provider unhealthy for transient upstream timeouts —
            # the proxy may recover. Re-raise so the task runner can classify
            # the failure as upstream_timeout rather than permanent.
            raise
        except Exception as e:
            self._provider_health[provider.value] = False
            raise

    # --- OpenRouter (OpenAI-compatible) ---

    async def _call_openrouter(self, model: str, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = self._to_openai_tools(request.tools)

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "HTTP-Referer": "https://github.com/linnana8888888/code-play",
            "X-Title": "Code PLAY Studio",
            "Content-Type": "application/json",
        }

        resp = await self._post_with_retry(
            f"{settings.openrouter_base_url}/chat/completions",
            json=payload,
            headers=headers,
            provider="openrouter",
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_openai_response(data, Provider.OPENROUTER)

    # --- oMLX (OpenAI-compatible local) ---

    async def _call_omlx(self, model: str, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if request.tools:
            payload["tools"] = self._to_openai_tools(request.tools)

        # oMLX uses api key from settings
        headers = {"Content-Type": "application/json"}
        if settings.omlx_api_key:
            headers["Authorization"] = f"Bearer {settings.omlx_api_key}"

        resp = await self._post_with_retry(
            f"{settings.omlx_base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
            provider="omlx",
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_openai_response(data, Provider.OMLX)

    # --- OpenAI via LEGO proxy (Azure deployment, chat completions) ---

    async def _call_openai(self, model: str, request: LLMRequest) -> LLMResponse:
        # GPT-5 is a reasoning model: `reasoning_tokens` count against output budget,
        # so tiny caps return empty content. Enforce a floor.
        max_completion = max(request.max_tokens or 0, 4096)
        payload: dict = {
            "messages": request.messages,
            "max_completion_tokens": max_completion,
        }
        if request.tools:
            payload["tools"] = self._to_openai_tools(request.tools)

        base = settings.lego_openai_base_url.rstrip("/")
        url = (
            f"{base}/openai/deployments/{model}/chat/completions"
            f"?api-version={settings.lego_openai_api_version}"
        )
        headers = {
            "api-key": settings.anthropic_auth_token,
            "Content-Type": "application/json",
        }
        resp = await self._post_with_retry(url, json=payload, headers=headers, provider="openai")
        resp.raise_for_status()
        return self._parse_openai_response(resp.json(), Provider.OPENAI)

    # --- Anthropic (native format) ---

    async def _call_anthropic(self, model: str, request: LLMRequest) -> LLMResponse:
        # Extract system message, then translate the OpenAI-style conversation
        # (role="assistant" + tool_calls, role="tool" with tool_call_id) into
        # Anthropic's native tool_use / tool_result content blocks. Consecutive
        # tool results must collapse into a single user message.
        system_msg = ""
        raw_messages: list[dict] = []
        for msg in request.messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
            else:
                raw_messages.append(msg)

        user_messages: list[dict] = []
        for msg in raw_messages:
            role = msg.get("role")
            if role == "assistant":
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls and isinstance(content, (str, list)):
                    user_messages.append({"role": "assistant", "content": content})
                    continue
                blocks: list[dict] = []
                if isinstance(content, str) and content:
                    blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    blocks.extend(content)
                for tc in tool_calls:
                    fn = tc.get("function", {}) if "function" in tc else tc
                    import json as _json
                    args = fn.get("arguments", fn.get("input", {}))
                    if isinstance(args, str):
                        try:
                            args = _json.loads(args or "{}")
                        except Exception:
                            args = {"_raw": args}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": args,
                    })
                user_messages.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id") or msg.get("tool_use_id"),
                    "content": msg.get("content", ""),
                }
                if user_messages and user_messages[-1]["role"] == "user" \
                        and isinstance(user_messages[-1].get("content"), list) \
                        and user_messages[-1]["content"] \
                        and isinstance(user_messages[-1]["content"][0], dict) \
                        and user_messages[-1]["content"][0].get("type") == "tool_result":
                    user_messages[-1]["content"].append(block)
                else:
                    user_messages.append({"role": "user", "content": [block]})
            else:
                user_messages.append(msg)

        payload = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": user_messages,
        }
        if system_msg:
            payload["system"] = system_msg.strip()
        if request.tools:
            payload["tools"] = self._to_anthropic_tools(request.tools)

        headers = {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        # Proxy path (LEGO etc.) uses Bearer token; direct Anthropic uses x-api-key
        if settings.anthropic_auth_token:
            headers["Authorization"] = f"Bearer {settings.anthropic_auth_token}"
        elif settings.anthropic_api_key:
            headers["x-api-key"] = settings.anthropic_api_key

        base = settings.anthropic_base_url.rstrip("/")
        url = f"{base}/v1/messages" if not base.endswith("/v1/messages") else base
        resp = await self._post_with_retry(
            url,
            json=payload,
            headers=headers,
            provider="anthropic",
        )
        if resp.status_code >= 400:
            import json as _json, logging, pathlib
            dump = pathlib.Path("/tmp/anthropic_fail_payload.json")
            dump.write_text(_json.dumps(payload, indent=2, default=str))
            logging.getLogger(__name__).error(
                "Anthropic proxy %s: %s (payload → %s)", resp.status_code, resp.text[:2000], dump,
            )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_anthropic_response(data)

    # --- Format translation ---

    def _to_openai_tools(self, tools: list[dict]) -> list[dict]:
        """Convert our tool definitions to OpenAI function-calling format."""
        result = []
        for tool in tools:
            result.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            })
        return result

    def _to_anthropic_tools(self, tools: list[dict]) -> list[dict]:
        """Convert to Anthropic tool format."""
        result = []
        for tool in tools:
            result.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    def _parse_openai_response(self, data: dict, provider: Provider) -> LLMResponse:
        """Parse OpenAI-compatible response (OpenRouter, oMLX)."""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = data.get("usage", {})

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                args = tc["function"].get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=tc["function"]["name"],
                    arguments=args,
                ))

        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            model=data.get("model", ""),
            provider=provider,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cost_usd=0.0,  # calculated separately for paid models
            raw=data,
        )

    def _parse_anthropic_response(self, data: dict) -> LLMResponse:
        """Parse Anthropic native response."""
        content_text = ""
        tool_calls = []

        for block in data.get("content", []):
            if block["type"] == "text":
                content_text += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {}),
                ))

        usage = data.get("usage", {})
        return LLMResponse(
            content=content_text or None,
            tool_calls=tool_calls,
            model=data.get("model", ""),
            provider=Provider.ANTHROPIC,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cost_usd=0.0,
            raw=data,
        )

    # --- Provider resolution ---

    def _resolve_provider(self, model: str) -> Provider:
        if model.startswith("openrouter/"):
            return Provider.OPENROUTER
        elif model.startswith("omlx/"):
            return Provider.OMLX
        elif model.startswith("anthropic/"):
            return Provider.ANTHROPIC
        elif model.startswith("openai/"):
            return Provider.OPENAI
        return Provider.OMLX  # OpenRouter is retired; unknown prefixes default to local

    def _strip_provider_prefix(self, model: str) -> str:
        for prefix in ["openrouter/", "omlx/", "anthropic/", "openai/"]:
            if model.startswith(prefix):
                return model[len(prefix):]
        return model

    def get_health(self) -> dict[str, bool]:
        return dict(self._provider_health)


# Singleton
router = LLMRouter()
