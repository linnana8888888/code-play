"""LLM routing models."""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class Provider(str, Enum):
    OPENROUTER = "openrouter"
    OMLX = "omlx"
    ANTHROPIC = "anthropic"


class ToolCall(BaseModel):
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of executing a tool."""
    tool_call_id: str
    content: str
    is_error: bool = False


class LLMRequest(BaseModel):
    """Request to the LLM router."""
    messages: list[dict]
    model: str
    tools: list[dict] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 4096


class LLMResponse(BaseModel):
    """Response from the LLM router."""
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str = ""
    provider: Provider = Provider.OPENROUTER
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: dict = Field(default_factory=dict)
