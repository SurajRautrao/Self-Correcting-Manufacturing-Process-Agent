## Component specification

```json
{component_json}
```

## Operation / tool catalogue

```json
{catalogue_json}
```

## Required output

Return exactly one JSON object with these fields:

```json
{{
  "component_id": "{component_id}",
  "operations": [
    {{
      "operation_id": "OP1",
      "type": "<operation type from catalogue>",
      "target_features": ["<feature_id>"],
      "machine_id": "<machine_id from resources>",
      "tool_id": "<tool_id from resources>",
      "duration_min": 1.0
    }}
  ],
  "precedence": [["OP1", "OP2"]],
  "explanation": "<short explanation of the sequence>",
  "assumptions": ["<assumption>"],
  "uncertainties": ["<open question>"]
}}
```
