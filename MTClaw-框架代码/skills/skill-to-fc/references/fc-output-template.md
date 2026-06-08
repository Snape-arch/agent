# FC Output Template

Generator emits JSON in this shape:

```json
{
  "functions": [
    {
      "name": "screen_recorder_start",
      "description": "Start screen recording (from skill command mapping).",
      "parameters": {
        "type": "object",
        "properties": {
          "output_path": {
            "type": "string",
            "description": "Optional output file path for recording."
          }
        }
      }
    }
  ],
  "environment_hints": [
    "requires_x11_environment"
  ]
}
```

## Field rules

- `functions`: required array.
- `environment_hints`: required array, unique and sorted.
- `name`: required, snake_case-like, deterministic from skill name + action.
- `description`: required.
- `parameters`: required object schema.
  - Always `type: object`.
  - `properties` must be object.
  - `required` omitted when empty.

## Deterministic vs hybrid

- Deterministic mode is baseline source of truth for action extraction and filtering.
- Hybrid mode may refine semantics (description/parameters) but must pass deterministic validation.
- Hybrid mode must not:
  - add new function names
  - rename existing functions
  - break schema contract

## Current mapping examples

For `screen-recorder`:
- `start` -> optional `output_path`.
- `pause` / `resume` / `stop` / `status` -> empty properties object.

For media-like controls:
- `*_set` / `*_up` / `*_down` -> optional `value` integer (0-100).
