# Parsing Rules

## Modes

Converter supports two modes:

1. `deterministic` (default)
   - Script-only extraction and shaping.
2. `hybrid`
   - Deterministic extraction + optional LLM analysis merge + deterministic verification.

## Supported sections

Converter reads from target `SKILL.md`:

1. `## Command Mapping`
   - Markdown table with `User says` and `Command` columns.
2. `## Usage`
   - Fenced `bash` code blocks for command examples and argument hints.

If `## Usage` is missing, converter scans the whole document for `bash` code blocks.

## Fallback behavior

- If `Command Mapping` is missing/empty, converter falls back to inferred mappings from usage commands.
- If both mapping table and usage examples are unavailable, converter exits with error.

## Action extraction

Examples:
- `./scripts/screen-recorder.sh start` -> `start`
- `./media_control_hybrid.sh volume up 15` -> `volume_up`

## Formal action filtering

Actions containing blocked keywords are always excluded:
- `demo`, `test`, `setup`, `quick`, `comparison`, `diagnostic`, `diagnostics`, `example`

This filtering is enforced in both deterministic and hybrid modes.

## Parameter inference (deterministic baseline)

- `start` + usage containing `/path/to/output` -> optional `output_path: string`
- `*_set`, `*_up`, `*_down` -> optional `value: integer (0-100)`
- Others -> empty `properties` object

## Hybrid merge whitelist

LLM analysis can only request:

- `function_overrides.<function_name>.description`
- `function_overrides.<function_name>.parameters`
- `exclude_actions` (additional removal list)

Not allowed:
- renaming function names
- adding brand-new functions
- changing top-level output contract

## Naming

Function names follow:
- `<skill_name_normalized>_<action>`
- Example: `screen_recorder_start`

`skill_name_normalized` is derived from frontmatter `name` with `-` normalized to `_`.
