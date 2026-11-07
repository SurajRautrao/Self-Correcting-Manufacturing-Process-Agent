"""Deterministic scripted client for tests and offline experiments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scmpa.llm.base import ChatMessage, LLMError, LLMResponse


class ScriptedLLMClient:
    """Returns pre-defined replies in order. An ``Exception`` instance in the script is raised instead.

    Every call's messages and schema are recorded in :attr:`calls` for assertions.
    """

    def __init__(self, replies: Iterable[str | Exception], model: str = "scripted") -> None:
        self._replies = list(replies)
        self._model = model
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, messages: list[ChatMessage], *, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        self.calls.append({"messages": [dict(m) for m in messages], "json_schema": json_schema})
        if not self._replies:
            raise LLMError("scripted client has no replies left")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(text=reply, model=self._model, latency_s=0.0)
