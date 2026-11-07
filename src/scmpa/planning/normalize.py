"""Turn raw model text into a typed :class:`ProcessPlan`, or fail with a clear reason.

The normalizer only makes changes that do not alter planning content:

* extracts the JSON object from markdown fences or surrounding prose;
* sets system-owned fields (``plan_id``, ``schema_version``) and clears ``provenance``;
* drops keys the schema does not define (e.g. a model-added ``"notes"`` on the plan);
* wraps a bare string ``target_features`` into a one-element list;
* converts precedence edges written as ``{"before": a, "after": b}`` into ``[a, b]``.

Every such change is recorded in the returned notes. Anything else — missing
fields, wrong types, unparsable text — raises :class:`PlanningError`.
Semantic problems (unknown IDs, bad order, ...) are left to the validator.
"""

from __future__ import annotations

import json
import re
from typing import Any

from scmpa.io import InputValidationError, parse_model
from scmpa.planning.output_schema import SYSTEM_OWNED_PLAN_FIELDS
from scmpa.schemas import SCHEMA_VERSION, Operation, ProcessPlan

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_EDGE_KEY_PAIRS = (("before", "after"), ("from", "to"), ("predecessor", "successor"))


class PlanningError(ValueError):
    """Model output could not be turned into a schema-valid plan."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))


def extract_json(text: str) -> Any:
    """Parse the JSON payload from ``text``: whole text, else a fenced block, else the outermost ``{...}``."""
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    errors = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"line {exc.lineno} col {exc.colno}: {exc.msg}")
    preview = text.strip().replace("\n", " ")[:120]
    raise PlanningError([f"response is not valid JSON ({errors[0] if errors else 'empty response'}); starts with: {preview!r}"])


def normalize_plan_output(text: str, *, plan_id: str) -> tuple[ProcessPlan, list[str]]:
    """Return ``(plan, notes)`` for raw model ``text``; raise :class:`PlanningError` if unusable."""
    return normalize_plan_data(extract_json(text), plan_id=plan_id)


def normalize_plan_data(data: Any, *, plan_id: str) -> tuple[ProcessPlan, list[str]]:
    """Like :func:`normalize_plan_output` but for already-parsed JSON. ``data`` may be modified."""
    if not isinstance(data, dict):
        raise PlanningError([f"top-level JSON must be an object, got {type(data).__name__}"])
    notes: list[str] = []

    allowed_plan_keys = set(ProcessPlan.model_fields)
    for key in sorted(set(data) - allowed_plan_keys):
        notes.append(f"dropped unknown plan field {key!r}")
        del data[key]
    for key in sorted(SYSTEM_OWNED_PLAN_FIELDS & set(data)):
        notes.append(f"ignored model-supplied system field {key!r}")
    data["plan_id"] = plan_id
    data["schema_version"] = SCHEMA_VERSION
    data["provenance"] = None

    allowed_op_keys = set(Operation.model_fields)
    operations = data.get("operations")
    if isinstance(operations, list):
        for i, op in enumerate(operations):
            if not isinstance(op, dict):
                continue
            for key in sorted(set(op) - allowed_op_keys):
                notes.append(f"operations[{i}]: dropped unknown field {key!r}")
                del op[key]
            if isinstance(op.get("target_features"), str):
                notes.append(f"operations[{i}]: wrapped string target_features in a list")
                op["target_features"] = [op["target_features"]]

    precedence = data.get("precedence")
    if isinstance(precedence, list):
        for i, edge in enumerate(precedence):
            if not isinstance(edge, dict):
                continue
            for a, b in _EDGE_KEY_PAIRS:
                if set(edge) == {a, b}:
                    precedence[i] = [edge[a], edge[b]]
                    notes.append(f"precedence[{i}]: converted {{{a!r}, {b!r}}} object to [a, b]")
                    break

    try:
        plan = parse_model(ProcessPlan, data, "model output")
    except InputValidationError as exc:
        raise PlanningError(exc.issues) from exc
    return plan, notes
