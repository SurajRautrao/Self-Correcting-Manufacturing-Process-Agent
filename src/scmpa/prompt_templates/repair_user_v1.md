## Component specification

```json
{component_json}
```

## Operation / tool catalogue

```json
{catalogue_json}
```

## Current plan

```json
{plan_json}
```

## Rule checker findings ({violation_count} hard violation(s))

```json
{findings_json}
```

## Required output

Return exactly one JSON object:

```json
{{
  "status": "REPAIRED",
  "changes": ["<one sentence per change>"],
  "missing_information": [],
  "plan": {{
    "component_id": "{component_id}",
    "operations": [ ... complete operation list ... ],
    "precedence": [ ... ],
    "explanation": "<short explanation of the revised sequence>",
    "assumptions": [ ... ],
    "uncertainties": [ ... ]
  }}
}}
```

or, if a violation cannot be resolved with the supplied data:

```json
{{"status": "NEEDS_HUMAN_REVIEW", "changes": [], "missing_information": ["<what is missing>"]}}
```
