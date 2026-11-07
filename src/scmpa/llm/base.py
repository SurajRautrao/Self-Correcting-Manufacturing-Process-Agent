"""Provider-neutral LLM client interface.

The rest of the codebase depends only on :class:`LLMClient`; provider SDKs or
HTTP details live in adapter modules (e.g. :mod:`scmpa.llm.ollama`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """Text returned by a model plus metadata for run records."""

    text: str
    model: str
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class LLMError(RuntimeError):
    """Transport or provider failure (unreachable server, HTTP error, unknown model, timeout)."""


class LLMClient(Protocol):
    """Anything that can turn chat messages into text."""

    @property
    def model(self) -> str: ...

    def complete(self, messages: list[ChatMessage], *, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        """Return the model's reply. If ``json_schema`` is given and the provider supports
        structured output, the reply should be constrained to it. Raises :class:`LLMError`."""
        ...
