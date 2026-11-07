"""JSON schema the LLM must produce (sent to providers that support structured output).

It mirrors :class:`scmpa.schemas.ProcessPlan` minus system-owned fields
(``plan_id``, ``schema_version``, ``provenance``), which the normalizer sets.
It is written out flat (no ``$ref``) for maximum backend compatibility; a unit
test keeps it in sync with the Pydantic model.
"""

from __future__ import annotations

from typing import Any

#: Fields of ProcessPlan that the system assigns; the model never needs to produce them.
SYSTEM_OWNED_PLAN_FIELDS = frozenset({"plan_id", "schema_version", "provenance"})

_OPERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation_id": {"type": "string"},
        "type": {"type": "string"},
        "target_features": {"type": "array", "items": {"type": "string"}},
        "machine_id": {"type": "string"},
        "tool_id": {"type": "string"},
        "duration_min": {"type": "number"},
    },
    "required": ["operation_id", "type", "target_features", "machine_id", "tool_id", "duration_min"],
}

PLAN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "component_id": {"type": "string"},
        "operations": {"type": "array", "items": _OPERATION_SCHEMA},
        "precedence": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
        },
        "explanation": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["component_id", "operations", "precedence", "explanation", "assumptions", "uncertainties"],
}
