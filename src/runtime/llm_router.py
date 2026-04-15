"""LLM Router — multi-provider routing with fallback chains."""

import json
import httpx
from src.models.llm import LLMRequest, LLMResponse, ToolCall, Provider
from src.settings import settings


class LLMRouter:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=120.0)
        self._provider_health: dict[str, bool] = {
            "openrouter": True,
            "omlx": True,
            "anthropic": True,
        }

    async def close(self):
        await self._client.aclose()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route an LLM request to the appropriate provider."""
        provider = self._resolve_provider(request.model)
        model_id = self._strip_provider_prefix(request.model)

        try:
            if provider == Provider.OPENROUTER:
                return await self._call_openrouter(model_id, request)
            elif provider == Provider.OMLX:
                return await self._call_omlx(model_id, request)
            elif provider == Provider.ANTHROPIC:
                return await self._call_anthropic(model_id, request)
            else:
                raise ValueError(f"Unknown provider: {provider}")
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

        resp = await self._client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            json=payload,
            headers=headers,
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
        }
        if request.tools:
            payload["tools"] = self._to_openai_tools(request.tools)

        # oMLX uses api key from settings
        headers = {"Content-Type": "application/json"}
        if settings.omlx_api_key:
            headers["Authorization"] = f"Bearer {settings.omlx_api_key}"

        resp = await self._client.post(
            f"{settings.omlx_base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_openai_response(data, Provider.OMLX)

    # --- Anthropic (native format) ---

    async def _call_anthropic(self, model: str, request: LLMRequest) -> LLMResponse:
        # Extract system message from messages list
        system_msg = ""
        user_messages = []
        for msg in request.messages:
            if msg["role"] == "system":
                system_msg += msg["content"] + "\n"
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
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        resp = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers=headers,
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
        return Provider.OPENROUTER

    def _strip_provider_prefix(self, model: str) -> str:
        for prefix in ["openrouter/", "omlx/", "anthropic/"]:
            if model.startswith(prefix):
                return model[len(prefix):]
        return model

    def get_health(self) -> dict[str, bool]:
        return dict(self._provider_health)


# Singleton
router = LLMRouter()
