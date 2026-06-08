#!/usr/bin/env python3
"""
Convert SKILL.md command mappings into OpenAI Function Calling JSON.

Supports two modes:
- deterministic: script-only extraction and shaping
- hybrid: deterministic baseline + optional LLM semantic enrichment + strict verification
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _validate_function_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]+", name))


def validate_function_definition(function: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(function, dict):
        raise ValueError("function must be an object")

    name = function.get("name")
    if not isinstance(name, str) or not _validate_function_name(name):
        raise ValueError("function.name must contain only letters, numbers, and underscores")

    description = function.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("function.description must be a non-empty string")

    parameters = function.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        raise ValueError("function.parameters must be an object JSON Schema")

    one_of = parameters.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list) or not one_of:
            raise ValueError("function.parameters.oneOf must be a non-empty array")
        if not all(isinstance(branch, dict) for branch in one_of):
            raise ValueError("function.parameters.oneOf branches must be objects")

    return function


def load_generated_artifacts(path: Path) -> Tuple[Dict[str, Any], str]:
    data = load_json_file(path)
    function = validate_function_definition(data.get("function"))
    script = data.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError("generated artifact script must be a non-empty string")
    return function, script


def replace_function_jsonl(functions_path: Path, function: Dict[str, Any]) -> None:
    function = validate_function_definition(function)
    functions_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[Dict[str, Any]] = []
    if functions_path.exists():
        for lineno, raw_line in enumerate(functions_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
            except Exception as e:
                raise ValueError(f"failed parsing {functions_path}:{lineno}: {e}")
            if not isinstance(existing, dict):
                raise ValueError(f"invalid function object at {functions_path}:{lineno}")
            if existing.get("name") != function["name"]:
                lines.append(existing)

    lines.append(function)
    functions_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n",
        encoding="utf-8",
    )


def _backup_path(path: Path, timestamp: str) -> Path:
    candidate = path.with_name(f"{path.name}.bak-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{timestamp}-{counter}")
        counter += 1
    return candidate


def backup_existing_runtime_files(functions_path: Path, script_path: Path) -> List[Path]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: List[Path] = []
    for path in (functions_path, script_path):
        if not path.exists():
            continue
        backup = _backup_path(path, timestamp)
        shutil.copy2(path, backup)
        backups.append(backup)
    return backups


def restore_runtime_files(backups: List[Path]) -> None:
    for backup in backups:
        original_name = re.sub(r"\.bak-\d{8}-\d{6}(?:-\d+)?$", "", backup.name)
        shutil.copy2(backup, backup.with_name(original_name))


def install_runtime_artifacts(
    functions_path: Path,
    scripts_dir: Path,
    function: Dict[str, Any],
    script: str,
) -> List[Path]:
    function = validate_function_definition(function)
    if not isinstance(script, str) or not script.strip():
        raise ValueError("script must be a non-empty string")

    script_path = scripts_dir / f"{function['name']}.sh"
    functions_existed = functions_path.exists()
    script_existed = script_path.exists()
    backups = backup_existing_runtime_files(functions_path, script_path)
    try:
        replace_function_jsonl(functions_path, function)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        restore_runtime_files(backups)
        if not functions_existed and functions_path.exists():
            functions_path.unlink()
        if not script_existed and script_path.exists():
            script_path.unlink()
        raise
    return backups


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter_name(content: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        raise ValueError("SKILL.md missing valid YAML frontmatter")
    fm = m.group(1)
    name_m = re.search(r"^name:\s*([^\n]+)$", fm, re.MULTILINE)
    if not name_m:
        raise ValueError("SKILL.md frontmatter missing name")
    return name_m.group(1).strip().strip('"').strip("'")


def extract_section(content: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    m = re.search(pattern, content, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    rest = content[start:]
    next_h2 = re.search(r"^##\s+", rest, re.MULTILINE)
    if next_h2:
        return rest[: next_h2.start()]
    return rest


def parse_command_mapping(section: str) -> List[Tuple[str, str]]:
    lines = [ln.rstrip() for ln in section.splitlines() if ln.strip()]
    table_lines = [ln for ln in lines if ln.strip().startswith("|")]
    if len(table_lines) < 3:
        return []

    rows: List[Tuple[str, str]] = []
    for ln in table_lines[2:]:
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cols) < 2:
            continue
        user_says, command = cols[0], cols[1]
        rows.append((user_says, command))
    return rows


def extract_action_from_command(command_cell: str) -> str:
    command_cell = command_cell.replace("`", "").strip()

    # Handle shell command forms, e.g.:
    # ./scripts/screen-recorder.sh start
    # ./media_control_hybrid.sh volume up 15
    sh_match = re.search(r"\.sh\s+(.+)$", command_cell)
    if sh_match:
        tail = sh_match.group(1).strip()
        tokens = tail.split()
        if not tokens:
            return ""
        if len(tokens) >= 2 and tokens[0] in {"volume", "brightness", "audio"}:
            return f"{tokens[0]}_{tokens[1]}".lower()
        return tokens[0].strip().lower()

    # fallback: derive from command token itself (e.g. ./demo.sh -> demo)
    parts = command_cell.split()
    if not parts:
        return ""
    token = parts[-1].strip().lower()
    token = token.replace("./", "")
    if token.endswith(".sh"):
        token = token[:-3]
    return re.sub(r"[^a-z0-9_]+", "_", token).strip("_")


def parse_usage_commands(section: str) -> Dict[str, str]:
    # map action -> best example line (prefer richer line with args)
    result: Dict[str, str] = {}
    code_blocks = re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
    for block in code_blocks:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ".sh" not in line:
                continue
            action = extract_action_from_command(line)
            if not action:
                continue

            prev = result.get(action, "")
            preferred = (
                "/path/to/" in line
                or "[" in line
                or len(line.split()) > len(prev.split())
            )
            if not prev or preferred:
                result[action] = line
    return result


def is_formal_action(action: str) -> bool:
    blocked_keywords = {
        "demo",
        "test",
        "setup",
        "quick",
        "comparison",
        "diagnostic",
        "diagnostics",
        "example",
    }
    parts = set(action.split("_"))
    return blocked_keywords.isdisjoint(parts)


def infer_environment_hints(content: str) -> List[str]:
    hints: List[str] = []
    lower = content.lower()

    if "sudo" in lower:
        hints.append("requires_sudo_for_some_commands")
    if "/sys/class/backlight/" in content:
        hints.append("requires_backlight_device")
    if "pactl" in lower or "pulseaudio" in lower:
        hints.append("requires_pulseaudio_or_compatible_audio_stack")
    if "xdotool" in lower:
        hints.append("requires_xdotool_for_hardware_simulation")
    if "display" in lower or "x11" in lower:
        hints.append("requires_x11_environment")

    return sorted(set(hints))


def sanitize_skill_name(skill_name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", skill_name.replace("-", "_")).lower()


def build_parameters(action: str, usage_line: str) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    required: List[str] = []

    if action == "start" and usage_line and "/path/to/output" in usage_line:
        props["output_path"] = {
            "type": "string",
            "description": "Optional output file path for recording.",
        }

    if action.endswith("_set") or action.endswith("_up") or action.endswith("_down"):
        props["value"] = {
            "type": "integer",
            "description": "Numeric control value (typically percentage).",
            "minimum": 0,
            "maximum": 100,
        }

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": props,
    }
    if required:
        schema["required"] = required
    return schema


def build_description(action: str, user_says: str) -> str:
    action_desc = {
        "start": "Start screen recording",
        "pause": "Pause current screen recording",
        "resume": "Resume paused screen recording",
        "stop": "Stop recording and save output",
        "status": "Get recording status",
    }.get(action, f"Execute {action}")

    short_user = user_says.replace("`", "").strip()
    return f"{action_desc}. Trigger hints: {short_user}."


def deterministic_extract(skill_md_path: Path) -> Dict[str, Any]:
    content = read_text(skill_md_path)
    skill_name = parse_frontmatter_name(content)
    skill_prefix = sanitize_skill_name(skill_name)

    mapping_sec = extract_section(content, "Command Mapping")
    usage_sec = extract_section(content, "Usage")

    mappings = parse_command_mapping(mapping_sec)
    usage_source = usage_sec if usage_sec.strip() else content
    usage_by_action = parse_usage_commands(usage_source)

    mapping_source = "table"
    if not mappings:
        if not usage_by_action:
            raise ValueError("No valid rows found in '## Command Mapping' table and no command examples found")
        mapping_source = "usage_fallback"
        mappings = [
            (f"inferred from usage: {action}", action)
            for action in usage_by_action.keys()
        ]

    seen = set()
    candidates: List[Dict[str, Any]] = []

    for user_says, cmd_cell in mappings:
        action = extract_action_from_command(cmd_cell)
        if not action or action in seen:
            continue
        seen.add(action)

        fn = {
            "name": f"{skill_prefix}_{action}",
            "action": action,
            "source_user_says": user_says,
            "source_command": cmd_cell,
            "description": build_description(action, user_says),
            "parameters": build_parameters(action, usage_by_action.get(action, "")),
            "formal": is_formal_action(action),
        }
        candidates.append(fn)

    functions: List[Dict[str, Any]] = [
        {
            "name": c["name"],
            "description": c["description"],
            "parameters": c["parameters"],
        }
        for c in candidates
        if c.get("formal")
    ]

    ir = {
        "skill_name": skill_name,
        "skill_prefix": skill_prefix,
        "skill_md_path": str(skill_md_path),
        "mapping_source": mapping_source,
        "environment_hints": infer_environment_hints(content),
        "usage_by_action": usage_by_action,
        "candidates": candidates,
        "deterministic_result": {
            "functions": functions,
            "environment_hints": infer_environment_hints(content),
        },
    }
    return ir


def build_llm_analysis_payload(ir: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task": "Improve FC semantics while keeping deterministic contract",
        "allowed_overrides": {
            "function_overrides": {
                "<function_name>": {
                    "description": "string",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": ["optional"],
                    },
                }
            },
            "exclude_actions": ["action_name"],
        },
        "constraints": [
            "Do not rename function names",
            "Do not add brand new functions",
            "Parameters must remain JSON Schema object",
            "Non-formal actions are filtered regardless of LLM output",
        ],
        "input_ir": ir,
    }


def load_json_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to read JSON file {path}: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"JSON must be an object: {path}")
    return data


def _ensure_parameters_schema(parameters: Any, strict_verify: bool) -> Dict[str, Any]:
    if not isinstance(parameters, dict):
        if strict_verify:
            raise ValueError("Invalid parameters: must be object")
        return {"type": "object", "properties": {}}

    schema = dict(parameters)
    if schema.get("type") != "object":
        if strict_verify:
            raise ValueError("Invalid parameters.type: must be 'object'")
        schema["type"] = "object"

    props = schema.get("properties")
    if not isinstance(props, dict):
        if strict_verify:
            raise ValueError("Invalid parameters.properties: must be object")
        schema["properties"] = {}

    req = schema.get("required")
    if req is not None and not isinstance(req, list):
        if strict_verify:
            raise ValueError("Invalid parameters.required: must be array")
        schema.pop("required", None)

    return schema


def merge_and_validate(ir: Dict[str, Any], llm_analysis: Dict[str, Any] | None, strict_verify: bool) -> Dict[str, Any]:
    candidates = ir.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("Invalid IR: candidates must be list")

    deterministic_functions = {
        fn["name"]: fn
        for fn in ir.get("deterministic_result", {}).get("functions", [])
        if isinstance(fn, dict) and isinstance(fn.get("name"), str)
    }

    function_overrides = {}
    exclude_actions = set()
    if llm_analysis:
        raw_overrides = llm_analysis.get("function_overrides", {})
        if isinstance(raw_overrides, dict):
            function_overrides = raw_overrides

        raw_exclude = llm_analysis.get("exclude_actions", [])
        if isinstance(raw_exclude, list):
            exclude_actions = {str(x).strip().lower() for x in raw_exclude if str(x).strip()}

    merged_functions: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        action = str(candidate.get("action", "")).strip().lower()
        if not action:
            continue

        if not is_formal_action(action):
            continue

        if action in exclude_actions:
            continue

        name = str(candidate.get("name", "")).strip()
        base_fn = deterministic_functions.get(name)
        if not base_fn:
            continue

        fn = {
            "name": name,
            "description": str(base_fn.get("description", "")).strip(),
            "parameters": _ensure_parameters_schema(base_fn.get("parameters", {}), strict_verify),
        }

        ov = function_overrides.get(name)
        if isinstance(ov, dict):
            desc = ov.get("description")
            if isinstance(desc, str) and desc.strip():
                fn["description"] = desc.strip()

            if "parameters" in ov:
                fn["parameters"] = _ensure_parameters_schema(ov.get("parameters"), strict_verify)

        # final name validation (never allow renamed/additional symbols)
        expected_prefix = f"{ir.get('skill_prefix', '')}_"
        if not fn["name"].startswith(expected_prefix):
            if strict_verify:
                raise ValueError(f"Invalid function name prefix: {fn['name']}")
            fn["name"] = name

        merged_functions.append(fn)

    return {
        "functions": merged_functions,
        "environment_hints": sorted(set(ir.get("environment_hints", []))),
    }


def convert(
    skill_md_path: Path,
    mode: str,
    llm_analysis_json: Path | None,
    emit_ir: Path | None,
    strict_verify: bool,
) -> Dict[str, Any]:
    ir = deterministic_extract(skill_md_path)

    if emit_ir:
        payload = build_llm_analysis_payload(ir)
        emit_ir.parent.mkdir(parents=True, exist_ok=True)
        emit_ir.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if mode == "deterministic":
        return ir["deterministic_result"]

    llm_analysis = None
    if llm_analysis_json:
        llm_analysis = load_json_file(llm_analysis_json)

    return merge_and_validate(ir, llm_analysis, strict_verify)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert SKILL.md to OpenAI FC JSON")
    parser.add_argument("--skill-md", help="Path to target SKILL.md")
    parser.add_argument("--out", help="Path to output JSON file")
    parser.add_argument(
        "--mode",
        choices=["deterministic", "hybrid"],
        default="deterministic",
        help="Conversion mode (default: deterministic)",
    )
    parser.add_argument(
        "--llm-analysis-json",
        help="Path to LLM analysis JSON (used in hybrid mode)",
    )
    parser.add_argument(
        "--emit-ir",
        help="Path to write intermediate analysis payload JSON",
    )
    parser.add_argument(
        "--strict-verify",
        action="store_true",
        help="Fail on invalid LLM analysis fields instead of auto-normalizing",
    )
    parser.add_argument(
        "--install-runtime-artifacts",
        help="Install generated Function Router artifacts JSON into the runtime directory",
    )
    parser.add_argument(
        "--functions-jsonl",
        default="~/.function-router/functions.jsonl",
        help="Runtime functions.jsonl path for --install-runtime-artifacts",
    )
    parser.add_argument(
        "--scripts-dir",
        default="~/.function-router/scripts",
        help="Runtime scripts directory for --install-runtime-artifacts",
    )
    args = parser.parse_args()

    if args.install_runtime_artifacts:
        artifacts_path = Path(args.install_runtime_artifacts).expanduser().resolve()
        functions_path = Path(args.functions_jsonl).expanduser().resolve()
        scripts_dir = Path(args.scripts_dir).expanduser().resolve()
        try:
            function, script = load_generated_artifacts(artifacts_path)
            backups = install_runtime_artifacts(functions_path, scripts_dir, function, script)
        except Exception as e:
            print(f"ERROR: {e}")
            return 1
        print(f"OK: installed {function['name']} into {functions_path}")
        print(f"Script: {scripts_dir / (function['name'] + '.sh')}")
        for backup in backups:
            print(f"Backup: {backup}")
        return 0

    if not args.skill_md or not args.out:
        print("ERROR: --skill-md and --out are required unless --install-runtime-artifacts is used")
        return 1

    skill_md = Path(args.skill_md).resolve()
    out = Path(args.out).resolve()
    llm_path = Path(args.llm_analysis_json).resolve() if args.llm_analysis_json else None
    emit_ir = Path(args.emit_ir).resolve() if args.emit_ir else None

    if not skill_md.exists():
        print(f"ERROR: skill md not found: {skill_md}")
        return 1

    if args.mode == "deterministic" and llm_path:
        print("WARN: --llm-analysis-json is ignored in deterministic mode")

    if llm_path and not llm_path.exists():
        print(f"ERROR: llm analysis json not found: {llm_path}")
        return 1

    try:
        result = convert(
            skill_md_path=skill_md,
            mode=args.mode,
            llm_analysis_json=llm_path,
            emit_ir=emit_ir,
            strict_verify=args.strict_verify,
        )
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: wrote {out}")
    print(f"Functions: {len(result.get('functions', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
