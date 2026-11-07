"""Ollama adapter using the local REST API (``POST /api/chat``). Standard library only."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from scmpa.llm.base import ChatMessage, LLMError, LLMResponse

DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class OllamaConfig:
    """Connection and sampling settings. ``seed`` + ``temperature`` make runs repeatable where the backend allows."""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    temperature: float = 0.0
    seed: int | None = 0
    num_ctx: int = 8192
    timeout_s: float = 600.0
    #: Thinking-mode toggle for models that support it; ``None`` leaves the model default.
    think: bool | None = False
    extra_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides: Any) -> OllamaConfig:
        """Build from ``SCMPA_LLM_MODEL`` / ``OLLAMA_BASE_URL`` environment variables, then apply overrides."""
        values: dict[str, Any] = {}
        if model := os.environ.get("SCMPA_LLM_MODEL"):
            values["model"] = model
        if base_url := os.environ.get("OLLAMA_BASE_URL"):
            values["base_url"] = base_url
        values.update(overrides)
        return cls(**values)


class OllamaClient:
    """:class:`~scmpa.llm.base.LLMClient` implementation for a local or remote Ollama server."""

    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig.from_env()

    @property
    def model(self) -> str:
        return self.config.model

    def build_request(self, messages: list[ChatMessage], json_schema: dict[str, Any] | None) -> dict[str, Any]:
        """The JSON body sent to ``/api/chat`` (exposed for testing and run logs)."""
        options: dict[str, Any] = {"temperature": self.config.temperature, "num_ctx": self.config.num_ctx}
        if self.config.seed is not None:
            options["seed"] = self.config.seed
        options.update(self.config.extra_options)
        body: dict[str, Any] = {"model": self.config.model, "messages": list(messages), "stream": False, "options": options}
        if json_schema is not None:
            body["format"] = json_schema
        if self.config.think is not None:
            body["think"] = self.config.think
        return body

    def complete(self, messages: list[ChatMessage], *, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        body = self.build_request(messages, json_schema)
        url = self.config.base_url.rstrip("/") + "/api/chat"
        request = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"Ollama HTTP {exc.code} for model {self.model!r}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"cannot reach Ollama at {self.config.base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(f"Ollama request timed out after {self.config.timeout_s}s") from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"Ollama returned a non-JSON response: {exc}") from exc
        latency = time.perf_counter() - start

        if "error" in payload:
            raise LLMError(f"Ollama error for model {self.model!r}: {payload['error']}")
        try:
            text = payload["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMError(f"unexpected Ollama response shape: keys={sorted(payload)}") from exc
        return LLMResponse(
            text=text,
            model=payload.get("model", self.model),
            latency_s=latency,
            prompt_tokens=payload.get("prompt_eval_count"),
            completion_tokens=payload.get("eval_count"),
            raw={k: v for k, v in payload.items() if k != "message"},
        )
