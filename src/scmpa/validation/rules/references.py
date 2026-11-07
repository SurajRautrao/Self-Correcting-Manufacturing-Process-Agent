"""Reference and compatibility rules: R1–R5 and R7.

To avoid cascades that would confuse the repair agent, a rule skips an
operation whose inputs are already reported by a more basic rule (e.g. R3
machine capability is not evaluated when R1 says the operation type is
unknown or R2 says the machine does not exist).
"""

from __future__ import annotations

from scmpa.schemas import Operation, ProcessPlan, Violation
from scmpa.validation.context import ValidationContext
from scmpa.validation.rules.coverage import uncovered_required_features

R1 = "R1_OPERATION_TYPE"
R2 = "R2_MACHINE_EXISTS"
R3 = "R3_MACHINE_CAPABILITY"
R4 = "R4_TOOL_EXISTS"
R5 = "R5_TOOL_COMPATIBILITY"
R7 = "R7_FEATURE_REFERENCE"


def operation_is_removable(plan: ProcessPlan, ctx: ValidationContext, op: Operation) -> bool:
    """True if dropping ``op`` leaves every currently covered required feature covered.

    An operation with no capable machine or compatible tool only blocks repair
    (``repairable=False``) when it is *needed*. An optional extra operation
    (e.g. spot drilling where no spot drill exists) can simply be removed.
    """
    without = plan.model_copy(update={"operations": [o for o in plan.operations if o.operation_id != op.operation_id]})
    return set(uncovered_required_features(without, ctx)) <= set(uncovered_required_features(plan, ctx))


def check_operation_type(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R1: every operation type belongs to the catalogue."""
    out = []
    for op in plan.operations:
        if op.type in ctx.operation_types:
            continue
        suggestions = sorted(
            {t for fid in op.target_features if (f := ctx.features.get(fid)) for t in ctx.suitable_operation_types(f)}
        )
        hint = (
            f"Replace {op.type!r} with a catalogue operation suitable for the target feature(s), e.g. {suggestions}."
            if suggestions
            else "Replace the operation type with one from the catalogue."
        )
        out.append(
            Violation(
                rule_id=R1,
                severity="hard",
                operation_id=op.operation_id,
                message=f"Operation type {op.type!r} is not in the operation catalogue.",
                evidence={"operation_type": op.type, "allowed_operation_types": list(ctx.catalogue.operation_types)},
                repair_hint=hint,
            )
        )
    return out


def check_machine_exists(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R2: every operation references an available machine."""
    out = []
    for op in plan.operations:
        if op.machine_id in ctx.machines:
            continue
        capable = ctx.capable_machines(op.type)
        out.append(
            Violation(
                rule_id=R2,
                severity="hard",
                operation_id=op.operation_id,
                message=f"Machine {op.machine_id!r} is not among the available machines.",
                evidence={"selected_machine": op.machine_id, "available_machines": sorted(ctx.machines)},
                repair_hint=(
                    f"Use an available machine capable of {op.type!r}: {capable}."
                    if capable
                    else f"Use one of the available machines: {sorted(ctx.machines)}."
                ),
            )
        )
    return out


def check_machine_capability(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R3: the referenced machine declares the operation type as a capability."""
    out = []
    for op in plan.operations:
        machine = ctx.machines.get(op.machine_id)
        if machine is None or op.type not in ctx.operation_types or op.type in machine.capabilities:
            continue
        capable = ctx.capable_machines(op.type)
        removable = not capable and operation_is_removable(plan, ctx, op)
        if capable:
            hint = f"Assign a machine capable of {op.type!r}: {capable}."
        elif removable:
            hint = f"No available machine can perform {op.type!r}, but {op.operation_id} is not needed for coverage: remove it."
        else:
            hint = f"No available machine can perform {op.type!r}; human review needed."
        out.append(
            Violation(
                rule_id=R3,
                severity="hard",
                operation_id=op.operation_id,
                message=f"Machine {op.machine_id!r} cannot perform {op.type!r}.",
                evidence={
                    "selected_machine": op.machine_id,
                    "operation_type": op.type,
                    "machine_capabilities": list(machine.capabilities),
                    "capable_machines": capable,
                    "operation_removable": removable,
                },
                repair_hint=hint,
                repairable=bool(capable) or removable,
            )
        )
    return out


def check_tool_exists(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R4: every operation references a tool in the available tool catalogue."""
    out = []
    for op in plan.operations:
        if op.tool_id in ctx.tools:
            continue
        compatible = ctx.compatible_tools(op.type)
        out.append(
            Violation(
                rule_id=R4,
                severity="hard",
                operation_id=op.operation_id,
                message=f"Tool {op.tool_id!r} is not among the available tools.",
                evidence={"selected_tool": op.tool_id, "available_tools": sorted(ctx.tools)},
                repair_hint=(
                    f"Use an available tool compatible with {op.type!r}: {compatible}."
                    if compatible
                    else f"Use one of the available tools: {sorted(ctx.tools)}."
                ),
            )
        )
    return out


def check_tool_compatibility(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R5: the tool's type is compatible with the operation type (explicit catalogue map)."""
    out = []
    for op in plan.operations:
        tool = ctx.tools.get(op.tool_id)
        if tool is None or op.type not in ctx.operation_types:
            continue
        allowed = ctx.catalogue.tool_compatibility[op.type]
        if tool.type in allowed:
            continue
        compatible = ctx.compatible_tools(op.type)
        removable = not compatible and operation_is_removable(plan, ctx, op)
        if compatible:
            hint = f"Select a compatible tool: {compatible}."
        elif removable:
            hint = f"No available tool of type {allowed} exists, but {op.operation_id} is not needed for coverage: remove it."
        else:
            hint = f"No available tool of type {allowed} exists; human review needed."
        out.append(
            Violation(
                rule_id=R5,
                severity="hard",
                operation_id=op.operation_id,
                message=f"Tool {op.tool_id!r} (type {tool.type!r}) is incompatible with {op.type!r}.",
                evidence={
                    "selected_tool": op.tool_id,
                    "selected_tool_type": tool.type,
                    "allowed_tool_types": list(allowed),
                    "compatible_available_tools": compatible,
                    "operation_removable": removable,
                },
                repair_hint=hint,
                repairable=bool(compatible) or removable,
            )
        )
    return out


def check_feature_references(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R7: each operation target references a feature defined in the component."""
    out = []
    for op in plan.operations:
        for fid in op.target_features:
            if fid in ctx.features:
                continue
            out.append(
                Violation(
                    rule_id=R7,
                    severity="hard",
                    operation_id=op.operation_id,
                    feature_id=fid,
                    message=f"Operation targets unknown feature {fid!r}.",
                    evidence={"unknown_feature": fid, "known_features": list(ctx.features)},
                    repair_hint="Target only features defined in the component input.",
                )
            )
    return out
