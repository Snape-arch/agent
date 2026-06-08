---
name: skill-to-fc
description: Convert a script-backed skill into Function Router runtime artifacts. Use when users want a skill exposed through .function-router as an OpenAI function plus matching shell wrapper.
---

# Skill to FC

Convert a script-backed skill into Function Router runtime artifacts:

- one OpenAI-compatible function definition for `~/.function-router/functions.jsonl`
- one matching shell wrapper at `~/.function-router/scripts/<function_name>.sh`

This is an LLM-led conversion workflow. The helper script validates and installs generated artifacts, but Claude must read the target skill, understand its scripts, and author the function schema and wrapper.

## When to use

Use this skill when the user asks to expose an existing skill through `.function-router`, generate FC/schema from a skill, or create/update the runtime `functions.jsonl` and `.sh` wrapper for a skill.

Do not use this for Debian packaging defaults. Runtime conversion only targets the user's active `.function-router` directory.

## Workflow

1. Inspect the target skill.
   - Read its `SKILL.md`.
   - Read referenced scripts under the skill's `scripts/` directory.
   - Identify the real runtime entrypoint, required arguments, environment assumptions, and output behavior.
2. Design the function schema.
   - Default function `name` to the sanitized skill name: lowercase, hyphen to underscore, only letters/numbers/underscores.
   - Start `description` from the skill frontmatter description, then refine it for routing intent.
   - Write descriptions for the model that will choose and call the function, not for developers reading the implementation.
   - Prefer positive descriptions: say what the function or field is for, and avoid or minimize "do not use for..." style negative descriptions.
   - Do not expose internal skill implementation details such as script names, process control mechanics, temporary files, or command-line plumbing unless the user must supply that value.
   - Include only parameters the router must supply at runtime.
   - Give parameters business-semantic names and descriptions that explain meaning and purpose from the user's task perspective.
   - Make different fields semantically distinct; avoid overlapping descriptions that could make the model confuse which field to fill.
   - Use `oneOf` when the script has multiple branches where different actions require different parameter sets.
3. Write the shell wrapper.
   - Filename must be `<function_name>.sh`.
   - Read JSON arguments from stdin.
   - Execute the skill script with the correct argv/env mapping.
   - Write JSON to stdout.
   - Write diagnostics to stderr.
   - Exit non-zero on failure.
4. Save generated artifacts to `/tmp/<skill>-fr-artifacts.json`.
5. Run the helper script to validate and install runtime artifacts with overwrite semantics.
6. Tell the user that Function Router may need a restart because tool definitions are loaded at startup.

## Generated artifact format

Create a JSON file shaped like this:

```json
{
  "function": {
    "name": "skill_name",
    "description": "Route user requests to the skill.",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  },
  "script": "#!/usr/bin/env bash\nset -euo pipefail\nargs=$(cat)\n...\n"
}
```

For complex script branches, prefer `oneOf` so the schema prevents invalid parameter combinations:

```json
{
  "type": "object",
  "oneOf": [
    {
      "properties": {"action": {"const": "status"}},
      "required": ["action"]
    },
    {
      "properties": {
        "action": {"const": "set"},
        "value": {"type": "integer", "minimum": 0, "maximum": 100}
      },
      "required": ["action", "value"]
    }
  ]
}
```

## Install/update runtime artifacts

After writing `/tmp/<skill>-fr-artifacts.json`, install it:

```bash
python skills/skill-to-fc/scripts/convert_skill_to_fc.py \
  --install-runtime-artifacts /tmp/<skill>-fr-artifacts.json
```

Optional test paths:

```bash
python skills/skill-to-fc/scripts/convert_skill_to_fc.py \
  --install-runtime-artifacts /tmp/<skill>-fr-artifacts.json \
  --functions-jsonl /tmp/function-router/functions.jsonl \
  --scripts-dir /tmp/function-router/scripts
```

Install behavior:

- validates `function.name`, `description`, and object `parameters`
- before overwriting, copies existing files next to their originals as `<filename>.bak-YYYYMMDD-HHMMSS`
- preserves unrelated `functions.jsonl` entries
- replaces any existing entry with the same `name`
- overwrites `scripts/<name>.sh`
- marks the wrapper executable
- prints every backup file path so the user can roll back manually

## Wrapper contract

A good wrapper follows this shape:

```bash
#!/usr/bin/env bash
set -euo pipefail

args_json=$(cat)
# Parse with python/jq, map JSON fields to the underlying skill command,
# run the command, and print one JSON object to stdout.
```

Output examples:

```json
{"result":"ok","tool_output":"completed"}
```

```json
{"error":"missing required parameter: action"}
```

Prefer preserving exact user-provided values. Do not guess paths, URLs, identifiers, or rewritten queries.

## Legacy conversion mode

The helper still supports the older deterministic/hybrid `--skill-md ... --out ...` flow for compatibility, but it is not the preferred path for script-backed skills. Use it only as a rough extraction aid; final conversion should be authored and reviewed by Claude using the workflow above.
