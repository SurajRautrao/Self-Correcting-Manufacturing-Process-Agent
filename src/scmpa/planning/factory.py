"""Build a planner from configuration (environment variables by default)."""

from __future__ import annotations

import os
from typing import Any

from scmpa.llm.ollama import OllamaClient, OllamaConfig
from scmpa.planning.mock import MockPlanner
from scmpa.planning.planner import LLMPlanner, Planner
from scmpa.prompts import PLANNER_PROMPT_VERSION

SUPPORTED_PROVIDERS = ("mock", "ollama")


def make_planner(provider: str | None = None, **options: Any) -> Planner:
    """Return a planner for ``provider`` (default: ``$SCMPA_LLM_PROVIDER`` or ``"mock"``).

    ``options`` go to :class:`OllamaConfig` for ``ollama`` (e.g. ``model``,
    ``seed``, ``temperature``) or to :class:`MockPlanner` for ``mock``
    (``faults``, ``seed``). ``max_attempts`` and ``prompt_version`` (default ``"v1"``) go to the LLM planner.
    """
    provider = (provider or os.environ.get("SCMPA_LLM_PROVIDER") or "mock").lower()
    if provider == "mock":
        return MockPlanner(**options)
    if provider == "ollama":
        max_attempts = options.pop("max_attempts", 2)
        prompt_version = options.pop("prompt_version", PLANNER_PROMPT_VERSION)
        return LLMPlanner(OllamaClient(OllamaConfig.from_env(**options)), max_attempts=max_attempts, prompt_version=prompt_version)
    raise ValueError(f"unsupported LLM provider {provider!r}; supported: {SUPPORTED_PROVIDERS}")
