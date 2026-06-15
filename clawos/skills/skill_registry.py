#!/usr/bin/env python3
"""Skill Registry - manage solidified skills for local sub-second execution."""
from __future__ import annotations
import json, os, re, time, sys, io
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).parent
REGISTRY_FILE = SKILLS_DIR / "skill_registry.jsonl"
FUNCTIONS_FILE = SKILLS_DIR.parent / "functions.jsonl"
SCRIPTS_DIR = SKILLS_DIR.parent / "scripts"
MAX_SKILL_NAME_LEN = 64
MAX_STEPS = 50
_skills_cache = None
_cache_mtime = 0.0

def _load_registry():
    global _skills_cache, _cache_mtime
    mtime = REGISTRY_FILE.stat().st_mtime if REGISTRY_FILE.exists() else 0.0
    if _skills_cache is not None and mtime == _cache_mtime:
        return _skills_cache
    skills = {}
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                obj = json.loads(line)
                name = obj.get("name", "")
                if name: skills[name] = obj
    _skills_cache = skills
    _cache_mtime = mtime
    return skills

def _save_registry(skills):
    global _cache_mtime
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for s in skills.values():
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    os.replace(tmp, REGISTRY_FILE)
    _cache_mtime = time.time()

def _sanitize_name(raw):
    name = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", raw.strip().lower())[:MAX_SKILL_NAME_LEN]
    return name.strip("_") or "unnamed_skill"

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def register_skill(name, description, steps, trigger_keywords=None, tags=None, category="general"):
    safe_name = _sanitize_name(name)
    validation = validate_skill_steps(steps)
    if validation["errors"]:
        return {"error": "Invalid skill steps", "validation": validation}
    skills = _load_registry()
    now = _now_iso()
    existing = skills.get(safe_name)
    version = (existing.get("version", 0) + 1) if existing else 1
    skill = {"name": safe_name, "display_name": name, "description": description,
             "steps": steps, "trigger_keywords": trigger_keywords or [],
             "tags": tags or [], "category": category, "version": version,
             "created_at": existing.get("created_at", now) if existing else now,
             "updated_at": now, "use_count": existing.get("use_count", 0) if existing else 0}
    skills[safe_name] = skill
    _save_registry(skills)
    _generate_replay_script(skill)
    return {"registered": True, "skill": skill}


def publish_skill_definition(skill):
    """Publish an already versioned definition without silently changing its version."""
    skill = deepcopy(skill)
    safe_name = _sanitize_name(str(skill.get("name") or skill.get("display_name") or ""))
    validation = validate_skill_steps(skill.get("steps"))
    if validation["errors"]:
        return {"error": "Invalid skill steps", "validation": validation}
    if int(skill.get("version", 0)) < 1:
        return {"error": "Skill version must be a positive integer"}
    now = _now_iso()
    skills = _load_registry()
    existing = skills.get(safe_name)
    skill.update({
        "name": safe_name,
        "display_name": str(skill.get("display_name") or safe_name),
        "description": str(skill.get("description") or ""),
        "trigger_keywords": list(skill.get("trigger_keywords") or []),
        "tags": list(skill.get("tags") or []),
        "category": str(skill.get("category") or "general"),
        "created_at": (
            str(skill.get("created_at") or "")
            or (existing.get("created_at", now) if existing else now)
        ),
        "updated_at": now,
        "use_count": int(skill.get("use_count", 0)),
    })
    skills[safe_name] = skill
    _save_registry(skills)
    _generate_replay_script(skill)
    return {"published": True, "skill": skill}


def get_skill(name):
    return _load_registry().get(_sanitize_name(name))

def list_skills(category=None):
    skills = list(_load_registry().values())
    if category: skills = [s for s in skills if s.get("category") == category]
    skills.sort(key=lambda s: s.get("use_count", 0), reverse=True)
    return skills

def execute_skill(name, params=None):
    skill = get_skill(name)
    if not skill: return {"error": f"Skill not found: {name}"}
    result = execute_skill_definition(skill, params=params)
    if not result.get("ok"):
        return result
    skill["use_count"] = skill.get("use_count", 0) + 1
    skill["last_used"] = _now_iso()
    skills = _load_registry()
    skills[skill["name"]] = skill
    _save_registry(skills)
    return result


def execute_skill_definition(skill, params=None, plan_only=False):
    """Validate and execute a candidate definition without publishing it."""
    validation = validate_skill_steps(skill.get("steps"))
    if validation["errors"]:
        return {"ok": False, "error": "Invalid skill steps", "validation": validation}
    name = str(skill.get("name") or skill.get("display_name") or "candidate")
    params = params or {}
    outputs = []
    step_outputs = {}
    for i, step in enumerate(skill["steps"]):
        tool_name = step.get("tool", "")
        args = deepcopy(step.get("args", {}))
        for k, v in params.items():
            if k in args: args[k] = v
        args = _resolve_refs(args, step_outputs, params)
        unresolved = _find_unresolved_refs(args)
        if plan_only:
            unresolved = [
                ref for ref in unresolved
                if not _is_prior_step_ref(ref, i)
            ]
        if unresolved:
            return {
                "ok": False,
                "skill": name,
                "failed_step": i,
                "error": f"Unresolved references: {', '.join(unresolved)}",
                "outputs": outputs,
            }
        t0 = time.perf_counter()
        result = (
            {"planned": True, "tool": tool_name, "args": args}
            if plan_only else _dispatch_tool(tool_name, args)
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        step_outputs[f"step_{i}"] = result
        outputs.append({"step": i, "tool": tool_name, "result": result, "elapsed_ms": elapsed_ms})
        if isinstance(result, dict) and result.get("error"):
            return {
                "ok": False,
                "skill": name,
                "failed_step": i,
                "error": str(result.get("error")),
                "outputs": outputs,
                "total_elapsed_ms": round(sum(o["elapsed_ms"] for o in outputs), 2),
            }
    total_ms = round(sum(o["elapsed_ms"] for o in outputs), 2)
    return {
        "ok": True,
        "skill": name,
        "version": int(skill.get("version", 0)),
        "mode": "plan" if plan_only else "execute",
        "steps": len(outputs),
        "outputs": outputs,
        "total_elapsed_ms": total_ms,
    }

def delete_skill(name):
    safe_name = _sanitize_name(name)
    skills = _load_registry()
    if safe_name not in skills: return {"error": f"Skill not found: {name}"}
    del skills[safe_name]
    _save_registry(skills)
    script = SKILLS_DIR / f"skill_{safe_name}.py"
    if script.exists(): script.unlink()
    return {"deleted": True, "name": name}

def match_skill_by_text(user_text):
    text_lower = user_text.lower()
    best = None; best_score = 0
    for skill in _load_registry().values():
        score = 0
        for kw in skill.get("trigger_keywords", []):
            kw_norm = str(kw).strip().lower()
            if not kw_norm or set(kw_norm) <= {"?", "？", "�"}:
                continue
            if kw_norm in text_lower: score += len(kw_norm)
        if skill.get("display_name", "").lower() in text_lower: score += 20
        if score > best_score: best_score = score; best = skill
    return best

def _generate_replay_script(skill):
    """Generate a standalone entry point that reuses the validated skill runtime."""
    script_path = SKILLS_DIR / f"skill_{skill['name']}.py"
    lines = [
        "#!/usr/bin/env python3",
        f"# Auto-generated replay script for: {skill['display_name']}",
        f"# Generated: {_now_iso()}",
        "import json",
        "import sys",
        "from pathlib import Path",
        "sys.path.insert(0, str(Path(__file__).resolve().parent))",
        "from skill_registry import execute_skill",
        "",
        "def main():",
        "    params = {}",
        "    if len(sys.argv) > 1:",
        "        params = json.loads(sys.argv[1])",
        f"    result = execute_skill({skill['name']!r}, params)",
        "    print(json.dumps(result, ensure_ascii=False, indent=2))",
        "    return 0 if result.get('ok') else 1",
        "",
        "if __name__ == '__main__':",
        "    raise SystemExit(main())",
        "",
    ]
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return script_path

def _dispatch_tool(tool_name, args):
    scripts_dir = SCRIPTS_DIR
    if str(scripts_dir) not in sys.path: sys.path.insert(0, str(scripts_dir))
    try:
        import tool_runner, importlib
        importlib.reload(tool_runner)
    except ImportError: return {"error": "tool_runner not found"}
    handlers = getattr(tool_runner, "handlers", {})
    if tool_name not in handlers: return {"error": f"Unknown tool: {tool_name}"}
    try:
        args = tool_runner.security_check(tool_name, args)
    except PermissionError as exc:
        return {"error": str(exc), "status": "denied"}
    old = sys.stdout; buf = io.StringIO(); sys.stdout = buf
    tool_runner.input_data = args; tool_runner.tool_name = tool_name
    try:
        handlers[tool_name]()
        out = buf.getvalue().strip()
        if out:
            try: return json.loads(out)
            except json.JSONDecodeError: return {"result": out[:2000]}
        return {"result": "ok"}
    except SystemExit:
        out = buf.getvalue().strip()
        if out:
            try: return json.loads(out)
            except json.JSONDecodeError: return {"result": out[:2000]}
        return {"result": "ok"}
    except Exception as e: return {"error": str(e)}
    finally: sys.stdout = old

def _resolve_refs(value, step_outputs, params=None):
    params = params or {}
    if isinstance(value, dict):
        return {k: _resolve_refs(v, step_outputs, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, step_outputs, params) for v in value]
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    param_match = re.fullmatch(r"\$param\.(\w+)", value)
    if param_match:
        return params.get(param_match.group(1), value)
    step_match = re.fullmatch(r"\$step_(\d+)\.(\w+)", value)
    if step_match:
        step_result = step_outputs.get(f"step_{step_match.group(1)}", {})
        return step_result.get(step_match.group(2), value)
    return value


def _find_unresolved_refs(value):
    if isinstance(value, dict):
        return [ref for item in value.values() for ref in _find_unresolved_refs(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in _find_unresolved_refs(item)]
    if isinstance(value, str) and value.startswith("$"):
        return [value]
    return []


def _is_prior_step_ref(ref, current_step):
    match = re.fullmatch(r"\$step_(\d+)\.\w+", str(ref))
    return bool(match and int(match.group(1)) < int(current_step))


def _available_tools():
    names = set()
    if FUNCTIONS_FILE.exists():
        with open(FUNCTIONS_FILE, "r", encoding="utf-8-sig") as f:
            for line in f:
                if line.strip():
                    names.add(json.loads(line).get("name", ""))
    return names


def validate_skill_steps(steps):
    errors = []
    warnings = []
    if not isinstance(steps, list) or not steps:
        return {"errors": ["Skill must have at least one step"], "warnings": []}
    if len(steps) > MAX_STEPS:
        errors.append(f"Skill exceeds maximum of {MAX_STEPS} steps")
    available = _available_tools()
    for i, step in enumerate(steps[:MAX_STEPS]):
        if not isinstance(step, dict):
            errors.append(f"Step {i} must be an object")
            continue
        tool = str(step.get("tool", "")).strip()
        args = step.get("args", {})
        if not tool:
            errors.append(f"Step {i} is missing tool")
        elif tool not in available:
            errors.append(f"Step {i} references unknown tool: {tool}")
        if not isinstance(args, dict):
            errors.append(f"Step {i} args must be an object")
        for ref in _find_unresolved_refs(args):
            if not re.fullmatch(r"\$(?:param\.\w+|step_\d+\.\w+)", ref):
                warnings.append(f"Step {i} has unsupported reference: {ref}")
    return {"errors": errors, "warnings": warnings}
