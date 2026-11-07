"""Rule type shared by all rule modules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from scmpa.schemas import ProcessPlan, Violation
from scmpa.validation.context import ValidationContext

RuleCheck = Callable[[ProcessPlan, ValidationContext], list[Violation]]


@dataclass(frozen=True)
class Rule:
    """A named, documented validator rule. ``check`` returns structured violations (empty = pass)."""

    rule_id: str
    title: str
    description: str
    check: RuleCheck
