"""Scenario-oriented tools for meetings, research, learning, office, and projects."""
from __future__ import annotations

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORYOS_DIR = os.path.join(BASE_DIR, "memoryos")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if MEMORYOS_DIR not in sys.path:
    sys.path.insert(0, MEMORYOS_DIR)


def _memory_db_path():
    path = os.path.abspath(os.path.expanduser(
        os.environ.get("CLAWOS_MEMORY_DB", os.path.join(BASE_DIR, "memoryos.db"))
    ))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _workspace_services():
    from memoryos.memory_store import MemoryStore
    from security.policy import ToolSecurityPolicy
    from workspace_services import WorkspaceServices
    return WorkspaceServices(MemoryStore(_memory_db_path()), ToolSecurityPolicy())


def _read_text_input(payload, text_key="text", file_key="file_path"):
    text = payload.get(text_key, "") or ""
    file_path = payload.get(file_key, "") or ""
    if file_path and os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    return str(text or "")


def _split_sentences(text, limit=80):
    parts = re.split(r"(?<=[。！？.!?])\s+|[\r\n]+", text)
    return [p.strip(" -\t") for p in parts if p.strip()][:limit]


def _keyword_lines(text, keywords, limit=12):
    hits = []
    for line in _split_sentences(text, limit=200):
        low = line.lower()
        if any(k.lower() in low or k in line for k in keywords):
            hits.append(line)
        if len(hits) >= limit:
            break
    return hits


def _write_optional_markdown(output_path, title, sections):
    if not output_path:
        return ""
    dirname = os.path.dirname(output_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    lines = [f"# {title}", ""]
    for heading, items in sections:
        lines.extend([f"## {heading}", ""])
        if isinstance(items, str):
            lines.extend([items, ""])
        else:
            lines.extend([f"- {item}" for item in (items or ["None"])])
            lines.append("")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return output_path


def meeting_action_items(payload):
    transcript = _read_text_input(payload, "transcript", "transcript_path")
    if not transcript:
        return {"error": "transcript or transcript_path required"}
    participants = payload.get("participants") or []
    title = payload.get("title", "Meeting Action Review")
    action_keywords = ["todo", "action", "owner", "负责", "待办", "跟进", "完成", "下周", "明天", "deadline", "due", "will"]
    decision_keywords = ["decide", "decision", "agreed", "决定", "确认", "同意", "结论", "采用"]
    risk_keywords = ["risk", "block", "issue", "delay", "风险", "阻塞", "问题", "延期", "依赖"]
    actions = _keyword_lines(transcript, action_keywords, 16) or _split_sentences(transcript, 6)
    decisions = _keyword_lines(transcript, decision_keywords, 10)
    risks = _keyword_lines(transcript, risk_keywords, 10)
    agenda = [f"Review: {item[:96]}" for item in (risks or actions[:3])]
    saved_to = _write_optional_markdown(payload.get("output_path", ""), title, [
        ("Decisions", decisions),
        ("Action Items", actions),
        ("Risks and Blockers", risks),
        ("Next Agenda", agenda),
    ])
    return {
        "title": title,
        "participants": participants,
        "decisions": decisions,
        "action_items": actions,
        "risks": risks,
        "next_agenda": agenda,
        "saved_to": saved_to,
    }


def paper_deep_read(payload):
    text = _read_text_input(payload, "text", "file_path")
    if not text:
        return {"error": "text or file_path required"}
    title = payload.get("title", "Paper Deep Read")
    method = _keyword_lines(text, ["method", "approach", "experiment", "dataset", "方法", "实验", "数据集", "模型"], 8)
    findings = _keyword_lines(text, ["result", "finding", "improve", "outperform", "结果", "发现", "提升", "优于"], 8)
    limitations = _keyword_lines(text, ["limit", "future work", "threat", "bias", "限制", "不足", "未来工作", "偏差"], 8)
    concepts = sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,6}", text)))[:24]
    questions = [f"What evidence supports: {item[:90]}?" for item in findings[:4]]
    questions += [f"How would you test this limitation: {item[:90]}?" for item in limitations[:3]]
    summary = _split_sentences(text, 5)
    saved_to = _write_optional_markdown(payload.get("output_path", ""), title, [
        ("Summary", summary),
        ("Method and Evidence", method),
        ("Key Findings", findings),
        ("Limitations", limitations),
        ("Concepts", concepts),
        ("Self-check Questions", questions),
    ])
    return {
        "title": title,
        "summary": summary,
        "method_evidence": method,
        "key_findings": findings,
        "limitations": limitations,
        "concepts": concepts,
        "self_check_questions": questions,
        "saved_to": saved_to,
    }


def exam_practice_builder(payload):
    topics = payload.get("topics") or []
    syllabus = payload.get("syllabus", "")
    count = int(payload.get("count", 8) or 8)
    difficulty = payload.get("difficulty", "mixed")
    if not topics and syllabus:
        topics = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_ -]{2,24}", syllabus)[:8]
    if not topics:
        return {"error": "topics or syllabus required"}
    questions = []
    for i in range(count):
        topic = topics[i % len(topics)]
        questions.append({
            "id": i + 1,
            "topic": topic,
            "difficulty": difficulty if difficulty != "mixed" else ["easy", "medium", "hard"][i % 3],
            "question": f"Explain or solve a representative problem about {topic}.",
            "answer_key": f"Cover definition, core method, common trap, and one example for {topic}.",
            "rubric": ["accuracy", "reasoning steps", "edge cases", "clear final answer"],
        })
    plan = [
        "Day 1: diagnose weak topics with closed-book recall.",
        "Day 2: redo wrong questions and write error causes.",
        "Day 3: mixed timed practice and formula/concept compression.",
    ]
    saved_to = _write_optional_markdown(payload.get("output_path", ""), "Exam Practice Set", [
        ("Topics", topics),
        ("Questions", [f"{q['id']}. [{q['difficulty']}] {q['question']} Answer: {q['answer_key']}" for q in questions]),
        ("Review Plan", plan),
    ])
    return {"topics": topics, "questions": questions, "review_plan": plan, "saved_to": saved_to}


def work_brief_builder(payload):
    context = _read_text_input(payload, "context", "file_path")
    title = payload.get("title", "Work Brief")
    goals = payload.get("goals") or _keyword_lines(context, ["goal", "目标", "交付", "deliver"], 6)
    blockers = _keyword_lines(context, ["block", "risk", "issue", "依赖", "风险", "阻塞", "问题"], 8)
    milestones = payload.get("milestones") or [
        "Clarify scope and acceptance criteria",
        "Prepare first deliverable draft",
        "Review, revise, and freeze handoff package",
    ]
    summary = _split_sentences(context, 5) if context else []
    saved_to = _write_optional_markdown(payload.get("output_path", ""), title, [
        ("Executive Summary", summary),
        ("Goals", goals),
        ("Stakeholders", payload.get("stakeholders") or []),
        ("Milestones", milestones),
        ("Risks", blockers),
    ])
    return {
        "title": title,
        "summary": summary,
        "goals": goals,
        "stakeholders": payload.get("stakeholders") or [],
        "milestones": milestones,
        "risks": blockers,
        "saved_to": saved_to,
    }


def research_experiment_plan(payload):
    question = payload.get("question", "")
    if not question:
        return {"error": "question required"}
    plan = {
        "question": question,
        "hypothesis": payload.get("hypothesis", ""),
        "datasets": payload.get("datasets") or [],
        "baselines": payload.get("baselines") or ["current system", "simple heuristic", "ablated variant"],
        "metrics": payload.get("metrics") or ["accuracy", "latency", "error analysis"],
        "steps": [
            "Freeze dataset split and random seed",
            "Run baseline and candidate under identical inputs",
            "Collect metrics, failures, latency, and qualitative traces",
            "Write conclusion with reproduction commands and artifact paths",
        ],
        "artifacts": ["README.md", "config.json", "results.json", "failure_cases.md"],
    }
    plan["saved_to"] = _write_optional_markdown(payload.get("output_path", ""), "Research Experiment Plan", [
        ("Question", [question]),
        ("Hypothesis", [plan["hypothesis"]] if plan["hypothesis"] else []),
        ("Datasets", plan["datasets"]),
        ("Baselines", plan["baselines"]),
        ("Metrics", plan["metrics"]),
        ("Steps", plan["steps"]),
        ("Artifacts", plan["artifacts"]),
    ])
    return plan


def meeting_workflow(payload):
    services = _workspace_services()
    action = payload.get("action", "create")
    if action == "create":
        return {"meeting": services.create_meeting(payload.get("title", "Untitled meeting"), payload.get("meeting_date", ""), payload.get("attendees", []), payload.get("agenda", []))}
    if action == "process":
        return {"meeting": services.process_meeting_transcript(payload.get("meeting_id"), payload.get("transcript", ""))}
    if action == "get":
        return {"meeting": services.get_meeting(payload.get("meeting_id"))}
    if action == "audio_import":
        return {"meeting": services.import_meeting_audio(payload.get("audio_path", ""), transcript_path=payload.get("transcript_path", ""), transcript=payload.get("transcript", ""), title=payload.get("title", ""), meeting_id=payload.get("meeting_id"))}
    if action == "connector_draft":
        return {"meeting": services.draft_meeting_connectors(payload.get("meeting_id"), payload.get("output_dir", ""), calendar=bool(payload.get("calendar", True)), email=bool(payload.get("email", True)), recipients=payload.get("recipients", []))}
    return {"meeting": {"error": f"unknown action: {action}"}}


def research_pdf(payload):
    services = _workspace_services()
    action = payload.get("action", "search")
    if action == "import":
        return {"document": services.import_research_pdf(payload.get("file_path", ""), payload.get("title", ""))}
    if action == "search":
        rows = services.search_research(payload.get("query", ""), payload.get("limit", 10))
        return {"results": rows, "count": len(rows)}
    if action == "validate_citations":
        return services.validate_citations(payload.get("citations", []))
    if action == "compare_matrix":
        return services.research_compare_matrix(payload.get("document_ids"), payload.get("query_terms", []))
    if action == "repro_workflow":
        return services.create_repro_workflow(payload.get("title", "Reproducible experiment"), question=payload.get("question", ""), steps=payload.get("steps"), output_path=payload.get("output_path", ""))
    if action == "learning_analysis":
        return services.generate_research_learning_analysis(document_id=payload.get("document_id"), file_path=payload.get("file_path", ""), title=payload.get("title", ""), output_dir=payload.get("output_dir", ""), formats=payload.get("formats"), depth=payload.get("depth", 5), question_count=payload.get("question_count", 50))
    return {"error": f"unknown action: {action}"}


def learning_workspace(payload):
    services = _workspace_services()
    action = payload.get("action", "create_goal")
    if action == "create_goal":
        result = services.create_learning_goal(payload.get("title", "Learning goal"), payload.get("description", ""), payload.get("target_date", ""), payload.get("topics", []))
    elif action == "review":
        result = services.record_learning_review(payload.get("item_id"), payload.get("score", 0), payload.get("evidence", ""), payload.get("notes", ""))
    elif action == "get":
        result = services.get_learning_goal(payload.get("goal_id"))
    elif action == "dependency":
        result = services.add_learning_dependency(payload.get("goal_id"), payload.get("source_topic", ""), payload.get("target_topic", ""), payload.get("relation", "depends_on"), payload.get("evidence", ""))
    elif action == "mistake":
        result = services.record_learning_mistake(payload.get("item_id"), payload.get("prompt", ""), payload.get("wrong_answer", ""), payload.get("correct_answer", ""), payload.get("evidence", ""))
    elif action == "graph":
        result = services.learning_graph(payload.get("goal_id"))
    elif action == "assessment":
        result = services.long_term_mastery(payload.get("goal_id"))
    else:
        result = {"error": f"unknown action: {action}"}
    return {"learning": result}


def office_artifact(payload):
    services = _workspace_services()
    action = payload.get("action", "")
    if action == "spreadsheet_create":
        result = services.create_spreadsheet(payload.get("output_path", ""), sheets=payload.get("sheets") or [], title=payload.get("title", ""))
    elif action == "spreadsheet_edit":
        result = services.edit_spreadsheet(payload.get("file_path", ""), updates=payload.get("updates") or [], output_path=payload.get("output_path", ""))
    elif action == "presentation_create":
        result = services.create_presentation(payload.get("output_path", ""), title=payload.get("title", ""), slides=payload.get("slides") or [])
    elif action == "presentation_edit":
        result = services.edit_presentation(payload.get("file_path", ""), replacements=payload.get("replacements") or {}, output_path=payload.get("output_path", ""))
    else:
        result = {"error": f"unknown action: {action}"}
    return {"artifact": result}


def git_workspace(payload):
    services = _workspace_services()
    action = payload.get("action", "snapshot")
    if action == "snapshot":
        result = services.git_snapshot(payload.get("path", ""))
    elif action == "commit_plan":
        result = services.prepare_commit_plan(payload.get("path", ""), payload.get("message", ""), payload.get("files"))
    elif action == "request_commit":
        result = services.create_git_change_request(payload.get("path", ""), payload.get("message", ""), payload.get("files"), created_by=payload.get("created_by", "agent"))
    elif action == "approve":
        result = services.approve_git_change_request(payload.get("request_id"), approved_by=payload.get("approved_by", "user"))
    elif action == "rollback":
        result = services.rollback_git_change_request(payload.get("request_id"), actor_id=payload.get("actor_id", "user"))
    else:
        result = {"error": f"unknown action: {action}"}
    return {"git": result}


def skill_governance(payload):
    from memoryos.memory_store import MemoryStore
    from skills.skill_evolution import SkillEvolutionManager
    manager = SkillEvolutionManager(MemoryStore(_memory_db_path()))
    action = payload.get("action", "manifest")
    version_id = payload.get("version_id")
    if action == "manifest":
        result = manager.dependency_manifest(version_id)
    elif action == "sign":
        result = manager.sign_version(version_id, signer=payload.get("signer", "agent"), secret=payload.get("secret", "clawos-local-signing"))
    elif action == "fresh_audit":
        result = manager.fresh_agent_audit(version_id, suite_id=payload.get("suite_id"))
    elif action == "canary":
        result = manager.start_canary(version_id, percent=payload.get("percent", 10), actor=payload.get("actor", "agent"))
    else:
        result = {"error": f"unknown action: {action}"}
    return {"skill_governance": result}


def template_list(payload):
    rows = _workspace_services().list_templates()
    return {"templates": rows, "count": len(rows)}


def template_instantiate(payload):
    return _workspace_services().instantiate_template(payload.get("name", ""), payload.get("target_path", ""), payload.get("parameters", {}), payload.get("version"))


HANDLERS = {
    "meeting_action_items": meeting_action_items,
    "paper_deep_read": paper_deep_read,
    "exam_practice_builder": exam_practice_builder,
    "work_brief_builder": work_brief_builder,
    "research_experiment_plan": research_experiment_plan,
    "meeting_workflow": meeting_workflow,
    "research_pdf": research_pdf,
    "learning_workspace": learning_workspace,
    "office_artifact": office_artifact,
    "git_workspace": git_workspace,
    "skill_governance": skill_governance,
    "template_list": template_list,
    "template_instantiate": template_instantiate,
}


def run(name, payload):
    handler = HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown scenario tool: {name}"}
    return handler(payload or {})


def print_result(name, payload):
    print(json.dumps(run(name, payload), ensure_ascii=False))
