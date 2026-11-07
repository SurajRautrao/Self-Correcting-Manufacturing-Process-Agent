"""Build a repair agent from configuration."""

from __future__ import annotations

from typing import Any

from scmpa.llm.ollama import OllamaClient, OllamaConfig
from scmpa.repair.repair_agent import LLMRepairAgent, RepairAgent
from scmpa.repair.rule_based import RuleBasedRepairAgent

SUPPORTED_REPAIR_AGENTS = ("rule_based", "ollama", "none")


def make_repair_agent(kind: str = "rule_based", **options: Any) -> RepairAgent | None:
    """``rule_based`` (deterministic), ``ollama`` (LLM; options go to OllamaConfig), or ``none`` (validate-only)."""
    kind = kind.lower()
    if kind == "rule_based":
        return RuleBasedRepairAgent()
    if kind == "ollama":
        max_attempts = options.pop("max_attempts", 2)
        return LLMRepairAgent(OllamaClient(OllamaConfig.from_env(**options)), max_attempts=max_attempts)
    if kind == "none":
        return None
    raise ValueError(f"unsupported repair agent {kind!r}; supported: {SUPPORTED_REPAIR_AGENTS}")
