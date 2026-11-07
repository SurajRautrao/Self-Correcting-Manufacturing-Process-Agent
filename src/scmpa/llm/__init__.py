"""Provider-neutral LLM access. Only adapters know about specific providers."""

from scmpa.llm.base import ChatMessage, LLMClient, LLMError, LLMResponse
from scmpa.llm.ollama import OllamaClient, OllamaConfig
from scmpa.llm.scripted import ScriptedLLMClient

__all__ = ["ChatMessage", "LLMClient", "LLMError", "LLMResponse", "OllamaClient", "OllamaConfig", "ScriptedLLMClient"]
