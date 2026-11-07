"""Loading and input validation for catalogue, component and plan JSON files.

Two layers of checks run on a component:

1. **Schema checks** (Pydantic): types, required fields, unknown fields,
   positive dimensions, duplicate IDs, references inside the file.
2. **Catalogue checks** (:func:`check_component_against_catalogue`): every
   feature type, tool type, machine capability and required operation type
   must exist in the catalogue, and declared precedence must be acyclic.

Any failure raises :class:`InputValidationError` listing *all* problems found,
each prefixed with its location, so a bad input file can be fixed in one pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from scmpa.graph import find_cycle
from scmpa.schemas import Catalogue, Component, ProcessPlan

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_CATALOGUE_PATH = DATA_DIR / "catalogue" / "catalogue_v1.json"
EXAMPLE_COMPONENTS_DIR = DATA_DIR / "examples" / "components"
REFERENCE_PLANS_DIR = DATA_DIR / "examples" / "reference_plans"

ModelT = TypeVar("ModelT", bound=BaseModel)


class InputValidationError(ValueError):
    """Raised when input data is malformed or references unknown IDs/types."""

    def __init__(self, source: str, issues: list[str]) -> None:
        self.source = source
        self.issues = issues
        bullet_list = "\n".join(f"  - {issue}" for issue in issues)
        super().__init__(f"Invalid input ({source}): {len(issues)} problem(s)\n{bullet_list}")


def _format_pydantic_errors(err: ValidationError) -> list[str]:
    issues = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        msg = e["msg"].removeprefix("Value error, ")
        issues.append(f"{loc}: {msg}")
    return issues


def read_json(path: str | Path) -> Any:
    """Read a JSON file, converting I/O and syntax errors into :class:`InputValidationError`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputValidationError(str(path), [f"cannot read file: {exc.strerror or exc}"]) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputValidationError(str(path), [f"malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]) from exc


def parse_model(model: type[ModelT], data: Any, source: str = "<data>") -> ModelT:
    """Validate ``data`` against ``model``, raising :class:`InputValidationError` with readable issues."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise InputValidationError(source, _format_pydantic_errors(exc)) from exc


def check_component_against_catalogue(component: Component, catalogue: Catalogue) -> list[str]:
    """Return problems where the component uses vocabulary the catalogue does not define.

    An empty list means the component is consistent with the catalogue.
    Note: this does *not* check that every required feature is producible with
    the available resources — an unproducible feature is a legitimate test case
    for the human-review path, not malformed input.
    """
    problems: list[str] = []
    op_types, tool_types = set(catalogue.operation_types), set(catalogue.tool_types)

    for i, f in enumerate(component.features):
        loc = f"features[{i}] ({f.feature_id})"
        suitable = catalogue.feature_types.get(f.type)
        if suitable is None:
            problems.append(f"{loc}: unknown feature type {f.type!r}; known: {sorted(catalogue.feature_types)}")
            continue
        for op in f.required_operation_types or []:
            if op not in op_types:
                problems.append(f"{loc}: required operation type {op!r} is not in the catalogue")
            elif op not in suitable:
                problems.append(f"{loc}: operation type {op!r} is not suitable for feature type {f.type!r}; suitable: {suitable}")

    for i, m in enumerate(component.resources.machines):
        if unknown := sorted(set(m.capabilities) - op_types):
            problems.append(f"resources.machines[{i}] ({m.machine_id}): unknown capabilities {unknown}")

    for i, t in enumerate(component.resources.tools):
        if t.type not in tool_types:
            problems.append(f"resources.tools[{i}] ({t.tool_id}): unknown tool type {t.type!r}; known: {sorted(tool_types)}")

    # Precedence: operation types must be ones the feature can receive; graph must be acyclic.
    graph: dict[str, set[str]] = {}
    for i, pc in enumerate(component.precedence_constraints):
        for end_name in ("before", "after"):
            end = getattr(pc, end_name)
            feature = component.feature(end.feature_id)
            if end.operation_type is None or feature is None:
                continue
            allowed = feature.required_operation_types or catalogue.feature_types.get(feature.type, [])
            if end.operation_type not in allowed:
                problems.append(
                    f"precedence_constraints[{i}].{end_name}: operation type {end.operation_type!r} "
                    f"is not applicable to feature {end.feature_id!r}; applicable: {allowed}"
                )
        a = f"{pc.before.feature_id}:{pc.before.operation_type or '*'}"
        b = f"{pc.after.feature_id}:{pc.after.operation_type or '*'}"
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set())
    # Feature-wide nodes ("F1:*") imply all op-specific nodes of that feature, and vice versa.
    by_feature: dict[str, list[str]] = {}
    for node in graph:
        by_feature.setdefault(node.split(":")[0], []).append(node)
    expanded = {n: set(s) for n, s in graph.items()}
    for nodes in by_feature.values():
        wildcard = [n for n in nodes if n.endswith(":*")]
        specific = [n for n in nodes if not n.endswith(":*")]
        for w in wildcard:
            for s in specific:
                # "all of F" before X implies "op on F" before X; X before "all of F" implies X before "op on F".
                expanded[s] |= graph[w]
                for src, dsts in graph.items():
                    if w in dsts:
                        expanded[src].add(s)
    if cycle := find_cycle(expanded):
        problems.append(f"precedence_constraints contain a cycle: {' -> '.join(cycle)}")

    return problems


def load_catalogue(path: str | Path = DEFAULT_CATALOGUE_PATH) -> Catalogue:
    """Load and validate a catalogue file."""
    return parse_model(Catalogue, read_json(path), str(path))


def validate_component(data: Any, catalogue: Catalogue, source: str = "<data>") -> Component:
    """Schema-validate component data and check it against the catalogue."""
    component = parse_model(Component, data, source)
    if problems := check_component_against_catalogue(component, catalogue):
        raise InputValidationError(source, problems)
    return component


def load_component(path: str | Path, catalogue: Catalogue | None = None) -> Component:
    """Load a component JSON file and validate it fully (schema + catalogue)."""
    catalogue = catalogue or load_catalogue()
    return validate_component(read_json(path), catalogue, str(path))


def load_plan(path: str | Path) -> ProcessPlan:
    """Load a process plan JSON file and validate its structure (not its feasibility)."""
    return parse_model(ProcessPlan, read_json(path), str(path))
