"""Provider-agnostic chat interface for tool-using models.

Messages and content blocks use the Bedrock Converse format (plain dicts), which
works across every Converse-capable model, so the transcript can be stored as-is.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # JSON Schema for the tool's input.
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    # The assistant message: {"role": "assistant", "content": [{"text": ...}, {"toolUse": ...}]}
    message: dict[str, Any]
    # "end_turn", "tool_use", "max_tokens", ...
    stop_reason: str
    input_tokens: int
    output_tokens: int


class LLMUnavailableError(Exception):
    """The model provider could not be reached or rejected the request."""


class LLMClient(Protocol):
    model_id: str

    def converse(
        self,
        system: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[ToolSpec],
        max_tokens: int,
    ) -> LLMResponse: ...
