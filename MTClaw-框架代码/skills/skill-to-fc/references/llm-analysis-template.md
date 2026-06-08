# LLM Analysis JSON Template

Use this template as input for `--llm-analysis-json` in hybrid mode.

```json
{
  "function_overrides": {
    "<function_name>": {
      "description": "Refined semantic description.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  "exclude_actions": []
}
```

## Allowed fields

- `function_overrides.<function_name>.description` (string)
- `function_overrides.<function_name>.parameters` (JSON Schema object)
- `exclude_actions` (array of action names)

## Constraints enforced by converter

- Cannot rename function names.
- Cannot add brand-new functions.
- `parameters.type` must be `object`.
- Non-formal actions are filtered even if not listed in `exclude_actions`.

## Typical workflow

1. Export IR:

```bash
python scripts/convert_skill_to_fc.py \
  --mode hybrid \
  --emit-ir /tmp/skill-ir.json \
  --skill-md ../target-skill/SKILL.md \
  --out /tmp/skill-hybrid.json
```

2. Ask Claude to produce `llm-analysis.json` using `/tmp/skill-ir.json`.

3. Merge with strict verification:

```bash
python scripts/convert_skill_to_fc.py \
  --mode hybrid \
  --llm-analysis-json /tmp/llm-analysis.json \
  --strict-verify \
  --skill-md ../target-skill/SKILL.md \
  --out ../target-skill/openai-fc.json
```
