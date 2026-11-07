"""Version-controlled prompt templates.

Prompts live as Markdown files in ``scmpa/prompt_templates/`` named
``<name>_<version>.md``. Each loaded template carries a content hash so a
run record pins exactly which prompt text was used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

PROMPT_DIR = Path(__file__).with_name("prompt_templates")

#: Current prompt version used by the planner.
PLANNER_PROMPT_VERSION = "v1"


@dataclass(frozen=True)
class PromptTemplate:
    """A named, versioned prompt. ``render`` uses ``str.format`` placeholders."""

    name: str
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    @property
    def ref(self) -> str:
        """Compact identifier for run logs, e.g. ``planner_system@v1#ab12...``."""
        return f"{self.name}@{self.version}#{self.sha256}"

    def render(self, **values: Any) -> str:
        return self.text.format(**values)


@cache
def load_prompt(name: str, version: str) -> PromptTemplate:
    """Load ``prompt_templates/<name>_<version>.md``. Raises ``FileNotFoundError`` if absent."""
    path = PROMPT_DIR / f"{name}_{version}.md"
    return PromptTemplate(name=name, version=version, text=path.read_text(encoding="utf-8"))
