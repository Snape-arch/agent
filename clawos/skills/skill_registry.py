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
    name = re.sub(r"[^a-zA-Z0-9_\\u4e00-\\u9fff]+", "_", raw.strip().lower())[:MAX_SKILL_NAME_LEN]
    return name.strip("_") or "unnamed_skill"

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def register_skill(name, description, steps, trigger_keywords=None, tags=None, category="general"):
    safe_name = _sanitize_name(name)
    if len(steps) > MAX_STEPS: return {"error": f"Too many steps"}
    if len(steps) == 0: return {"error": "Skill must have steps"}
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
    params = params or {}
    outputs = []
    step_outputs = {}
    for i, step in enumerate(skill["steps"]):
        tool_name = step.get("tool", "")
        args = deepcopy(step.get("args", {}))
        for k, v in params.items():
            if k in args: args[k] = v
        args = _resolve_refs(args, step_outputs)
        t0 = time.perf_counter()
        result = _dispatch_tool(tool_name, args)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        step_outputs[f"step_{i}"] = result
        outputs.append({"step": i, "tool": tool_name, "result": result, "elapsed_ms": elapsed_ms})
    skill["use_count"] = skill.get("use_count", 0) + 1
    skill["last_used"] = _now_iso()
    skills = _load_registry()
    skills[skill["name"]] = skill
    _save_registry(skills)
    total_ms = round(sum(o["elapsed_ms"] for o in outputs), 2)
    return {"skill": name, "steps": len(outputs), "outputs": outputs, "total_elapsed_ms": total_ms}

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
    """Generate replay script, resolving refs at generation time."""
    script_path = SKILLS_DIR / f"skill_{skill['name']}.py"
    prev_outputs = {}
    for i, step in enumerate(skill["steps"]):
        step_args = deepcopy(step.get("args", {}))
        resolved = _resolve_refs(step_args, prev_outputs)
        prev_outputs[f"step_{i}"] = dict(resolved, result="ok")
    lines = [
        "#!/usr/bin/env python3",
        f"# Auto-generated replay script for: {skill['display_name']}",
        f"# Generated: {_now_iso()}",
        "import json, sys, os",
        'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))',
        "from tool_runner import handlers", "", "def main():",
        "    params = {}",
        "    if len(sys.argv) > 1:",
        '        try: params = json.loads(sys.argv[1])',
        "        except: pass"]
    for i, step in enumerate(skill["steps"]):
        tool = step.get("tool", "")
        resolved = _resolve_refs(deepcopy(step.get("args", {})), prev_outputs)
        sargs = json.dumps(resolved, ensure_ascii=False)
        lines += [
            f"    # Step {i}: {tool}",
            "    import io, sys as _sys", "    _old = _sys.stdout",
            "    _sys.stdout = io.StringIO()", "    import tool_runner",
            f"    tool_runner.input_data = json.loads({sargs!r})",
            f"    tool_runner.tool_name = {tool!r}",
            f"    handlers[{tool!r}]()",
            "    print(f'[Step {i}]', _sys.stdout.getvalue().strip())",
            "    _sys.stdout = _old"]
    lines += ["", "if __name__ == '__main__':", "    main()", ""]
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return script_path

def _dispatch_tool(tool_name, args):
    scripts_dir = SKILLS_DIR.parent / "scripts"
    if str(scripts_dir) not in sys.path: sys.path.insert(0, str(scripts_dir))
    try:
        import tool_runner, importlib
        importlib.reload(tool_runner)
    except ImportError: return {"error": "tool_runner not found"}
    handlers = getattr(tool_runner, "handlers", {})
    if tool_name not in handlers: return {"error": f"Unknown tool: {tool_name}"}
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

def _resolve_refs(args, step_outputs):
    resolved = {}
    ref_pattern = re.compile(r"^\$step_(\d+)\.(\w+)$")
    for key, value in args.items():
        if isinstance(value, str) and value.startswith("$"):
            m = ref_pattern.match(value)
            if m:
                step_result = step_outputs.get(f"step_{m.group(1)}", {})
                resolved[key] = step_result.get(m.group(2), value)
            else: resolved[key] = value
        else: resolved[key] = value
    return resolved
