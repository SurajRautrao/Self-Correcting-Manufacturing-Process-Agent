# Assumptions and limits

This file lists every simplification in the SCMPA model. A plan judged "valid" by SCMPA is valid **only under these assumptions**.

## What SCMPA is not

- It does not generate G-code or anything machine-executable.
- It does not check geometry, tool access, collisions, fixturing or workholding.
- It does not use real cutting speeds, feeds, tolerances or surface-finish requirements.
- It makes no claim of production readiness or safety, and is not connected to any machine.

## Data-model simplifications (Milestone 0)

| Area | Simplification |
|---|---|
| Geometry | A component is a flat list of typed features with optional dimensions in mm. There is no CAD model, feature location, orientation or tolerance. |
| Setups | Not modelled. Examples assume a single setup unless stated otherwise. Transfers between machines have no cost. |
| Tools | Compatibility is decided by **tool type only**. Diameter, length, flute count and wear are ignored, so an 8 mm drill and a 5 mm drill are interchangeable to the validator. |
| Machines | A machine is a list of operation-type capabilities. Work envelope, spindle power and axes are ignored. |
| Feature coverage | Each feature type has a catalogue list of suitable operations. If a feature lists `required_operation_types`, all of them must be applied; otherwise one suitable *completing* operation counts as coverage. Spot drilling is preparatory (rule set v1.2): it never completes a hole on its own. |
| Face milling | Mapped only to face mills, although end mills can face small areas in practice. |
| Durations | Plan durations are illustrative estimates. They are not calculated from cutting data. |

## Operation order

SCMPA encodes **no universal precedence rule**. In particular, "face milling before drilling" is *not* a built-in rule. Ordering comes only from:

1. **Component-specific `precedence_constraints`** in each component file. Each has a mandatory `rationale`, and most are labelled *demo assumption*. A constraint can refer to a whole feature (`{"feature_id": "F1"}`) or to one operation on a feature (`{"feature_id": "F3", "operation_type": "drilling"}`).
2. **The plan's own `precedence` edges**, which must be acyclic and respected by the operation sequence.

The order of a plan's `operations` list is its proposed execution sequence.

The one ordering in the examples that holds almost universally is drilling the tap hole before cutting a thread (`demo_plate_002`). Even this is stored as component data, not code.

## Where each check lives

| Check | Stage |
|---|---|
| JSON syntax, field types, missing or unknown fields, positive dimensions | Input schema (M0) |
| Duplicate feature, machine, tool or operation IDs | Input / plan schema (M0) |
| Component uses feature, tool or operation types missing from the catalogue | Input catalogue check (M0) |
| Precedence constraints reference unknown features or inapplicable operations, or form a cycle | Input catalogue check (M0) |
| Plan references unknown machines, tools or features; bad operation types; incompatible tools; missing coverage; precedence and order errors; durations; completeness | Validator rules R1–R12 (M1) |

The input stage deliberately does **not** reject a component whose required feature cannot be produced with the available resources. That situation is a valid test case for the "needs human review" path.

## Data provenance

All examples are **synthetic**: hand-written toy specifications for testing the software. Reference plans were authored under each component's declared assumptions and have **not** been reviewed by a manufacturing expert. They are one valid sequence among possibly several. Results obtained on this data must not be presented as industrial performance.
