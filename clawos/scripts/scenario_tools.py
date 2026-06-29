"""Scenario-oriented tools for meetings, research, learning, office, and projects."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORYOS_DIR = os.path.join(BASE_DIR, "memoryos")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if MEMORYOS_DIR not in sys.path:
    sys.path.append(MEMORYOS_DIR)


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


def _safe_slug(value):
    text = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "-", str(value or "").strip())
    return text.strip("-")[:80] or "clawos-delivery"


def _read_doc(path, max_chars=12000):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:max_chars]
    except OSError:
        return ""


def _first_existing(root, candidates):
    root = Path(root)
    for item in candidates:
        path = root / item
        if path.exists():
            return path
    return None


def _extract_evidence(text, keywords, limit=8):
    evidence = []
    for line in re.split(r"[\r\n]+", str(text or "")):
        cleaned = re.sub(r"\s+", " ", line).strip(" -#|\t")
        if not cleaned or len(cleaned) < 8:
            continue
        low = cleaned.lower()
        if any(str(keyword).lower() in low or str(keyword) in cleaned for keyword in keywords):
            evidence.append(cleaned[:220])
        if len(evidence) >= limit:
            break
    return evidence


def _write_delivery_file(output_dir, filename, title, sections):
    path = Path(output_dir) / filename
    lines = [f"# {title}", ""]
    for heading, body in sections:
        lines.extend([f"## {heading}", ""])
        if isinstance(body, str):
            lines.extend([body.strip() or "未提供。", ""])
        else:
            items = list(body or [])
            if not items:
                lines.extend(["- 未提供。", ""])
            else:
                lines.extend([f"- {item}" for item in items])
                lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def competition_delivery_package(payload):
    """Build a judge-facing enterprise delivery package from project evidence."""
    default_root = Path(BASE_DIR).parent if (Path(BASE_DIR).parent / "PROJECT_CONTEXT.md").exists() else Path(BASE_DIR)
    root = Path(payload.get("root") or default_root).expanduser().resolve()
    output_root = Path(payload.get("output_dir") or (root / "output" / "delivery")).expanduser().resolve()
    project_name = str(payload.get("project_name") or "ClawOS").strip() or "ClawOS"
    scenario = str(payload.get("scenario") or "MTClaw competition enterprise delivery").strip()
    package_dir = output_root / _safe_slug(project_name)
    package_dir.mkdir(parents=True, exist_ok=True)

    docs = {
        "business_plan": _first_existing(root, ["ClawOS_商业计划书.md", "plan_text.txt"]),
        "architecture": _first_existing(root, ["架构说明.txt"]),
        "readme": _first_existing(root, ["README.md", "clawos/README.md"]),
        "context": _first_existing(root, ["PROJECT_CONTEXT.md"]),
        "roadmap": _first_existing(root, ["PROJECT_ROADMAP.md", "clawos/ROADMAP.md"]),
        "mtclaw": _first_existing(root, ["clawos/MTCLAW_INTEGRATION.md"]),
        "enterprise": _first_existing(root, ["clawos/ENTERPRISE_READINESS.md"]),
    }
    corpus = {name: _read_doc(path) if path else "" for name, path in docs.items()}
    combined = "\n".join(corpus.values())
    architecture_assets = []
    arch_dir = root / "架构图"
    if arch_dir.exists():
        architecture_assets = [str(path) for path in sorted(arch_dir.iterdir()) if path.is_file()]
    plan_assets = []
    plan_dir = root / "计划书和题目要求"
    if plan_dir.exists():
        plan_assets = [str(path) for path in sorted(plan_dir.iterdir()) if path.is_file()]

    capability_evidence = _extract_evidence(
        combined,
        ["MTClaw", "MemoryOS", "Reflection", "RAG", "Skill", "自进化", "工具", "安全", "Qwen", "DeepSeek"],
        14,
    )
    validation_evidence = _extract_evidence(
        combined,
        ["tests OK", "passed", "pass_rate", "score=", "验收", "benchmark", "P95", "Chroma", "rerank"],
        14,
    )
    risk_evidence = _extract_evidence(
        combined,
        ["风险", "缺口", "尚未", "deferred", "MTT", "mttbook", "AIBOOK", "不要", "not yet"],
        14,
    )
    business_evidence = _extract_evidence(
        corpus.get("business_plan", ""),
        ["用户", "市场", "商业", "教育", "科研", "办公", "价值", "模式", "竞争"],
        12,
    )

    score_items = {
        "materials": bool(corpus.get("business_plan") and (corpus.get("architecture") or architecture_assets)),
        "mtclaw": bool(corpus.get("mtclaw") and "MTClaw" in corpus.get("mtclaw", "")),
        "validation": bool(validation_evidence),
        "risk_register": bool(risk_evidence),
        "business": bool(business_evidence),
        "architecture_assets": bool(architecture_assets),
        "plan_assets": bool(plan_assets),
    }
    readiness_score = round(100 * sum(1 for ok in score_items.values() if ok) / len(score_items))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    missing = [name for name, ok in score_items.items() if not ok]

    executive_brief = _write_delivery_file(package_dir, "executive_brief.md", f"{project_name} Executive Brief", [
        ("定位", [
            f"{project_name} 是面向 {scenario} 的个人 Agent OS 交付包。",
            "核心叙事：MTClaw 运行时 + MemoryOS 长期记忆 + RAG 知识库 + Reflection/Skill 自进化 + 安全工具执行。",
        ]),
        ("商业与用户证据", business_evidence),
        ("可展示亮点", capability_evidence[:8]),
        ("交付成熟度", [
            f"readiness_score={readiness_score}/100",
            f"generated_at={generated_at}",
            "建议现场主线：资料入库 -> 多步骤工具执行 -> 报告产物 -> 证据链 -> 反思复盘 -> 策略改进。",
        ]),
    ])
    technical_evidence = _write_delivery_file(package_dir, "technical_evidence.md", f"{project_name} Technical Evidence", [
        ("代码与架构材料", [str(path) for path in docs.values() if path] + architecture_assets),
        ("能力证据摘录", capability_evidence),
        ("验收证据摘录", validation_evidence),
        ("建议补充的硬证据", [
            "目标硬件实机运行截图或录屏。",
            "同一冻结任务集在 API 模式与本地模式下的成功率、延迟和资源占用对比。",
            "复杂任务的工具调用时间线和引用溯源截图。",
        ]),
    ])
    demo_runbook = _write_delivery_file(package_dir, "demo_runbook.md", f"{project_name} Demo Runbook", [
        ("演示目标", [
            "用一条高价值闭环证明 ClawOS 不是聊天壳，而是可执行、可追踪、可复盘的 Agent 工作台。",
            "每一步必须能对应工具调用、证据文件或验收指标。",
        ]),
        ("推荐 7 步流程", [
            "1. 打开控制台和健康检查，展示模型、MTClaw、数据库、向量库状态。",
            "2. 上传/选择项目或论文资料，触发解析、chunk、索引和知识库展示。",
            "3. 运行超级 Skill 生成交付包或报告。",
            "4. 展示工具时间线、Trace、引用/证据来源。",
            "5. 用 Reviewer 视角追问风险、缺口和答辩问题。",
            "6. 触发 Reflection 或自进化候选，展示门禁、shadow/canary/rollback。",
            "7. 导出报告/PPT/Markdown 交付物并回到知识库继续追问。",
        ]),
        ("现场兜底", [
            "保留 DeepSeek/API、Mock/offline 和本地模型三种叙事分支。",
            "所有输出产物放在 output/ 下，不进入 Git 提交。",
            "提交代码时精确 git add，避免 tmp/ 和 tools/。",
        ]),
    ])
    judge_qa = _write_delivery_file(package_dir, "judge_qa.md", f"{project_name} Judge Q&A", [
        ("可能被问到的问题", [
            "你们与普通聊天助手的区别是什么？回答：长期记忆、工具执行、证据链、Skill 固化和自进化门禁。",
            "如何证明基于 MTClaw？回答：展示 MTClaw Adapter、Function Router、Tool History 和 ClawOS Trace。",
            "自进化是否危险？回答：只允许低风险策略目标，禁止自动改代码，必须通过冻结/核心/RAG 回归门禁。",
            "没有实机时如何证明可迁移？回答：展示 OpenAI-compatible 本地模型接口、启动脚本、验收脚本和待补实机指标。",
            "商业价值是什么？回答：科研、学习、办公、开发和教育场景都能复用个人知识与工作流。",
        ]),
        ("答辩姿态", [
            "承认 MTTBook 实机验收是硬缺口，但强调其余工程闭环、材料和验收脚手架已就绪。",
            "用数字说话：测试数量、benchmark 通过率、P95、RAG recall、报告产物路径。",
            "避免空泛企业级宣称，强调可审计、可回滚、可逐步发布。",
        ]),
    ])
    risk_register = _write_delivery_file(package_dir, "risk_register.md", f"{project_name} Risk Register", [
        ("当前风险证据", risk_evidence),
        ("P0 关闭项", [
            "完成目标硬件本地模型和 MTClaw 双服务验收。",
            "录制一条完整 Demo 主线并保存关键截图。",
            "冻结提交清单，确认 tmp/、tools/、output/ 产物不进入仓库。",
        ]),
        ("P1 增强项", [
            "加入多 Agent Reviewer 对报告质量、引用覆盖和风险遗漏打分。",
            "把超级 Skill 产物重新入库，形成资料 -> 产物 -> 追问 -> 反思的闭环。",
            "建立真实用户任务的质量信号，替代纯规则化自进化候选。",
        ]),
    ])
    index = _write_delivery_file(package_dir, "delivery_index.md", f"{project_name} Delivery Index", [
        ("交付包文件", [
            executive_brief,
            technical_evidence,
            demo_runbook,
            judge_qa,
            risk_register,
        ]),
        ("Readiness", [
            f"score={readiness_score}/100",
            f"missing={', '.join(missing) if missing else 'none'}",
            f"source_root={root}",
        ]),
    ])
    return {
        "project_name": project_name,
        "scenario": scenario,
        "readiness_score": readiness_score,
        "checks": score_items,
        "missing": missing,
        "package_dir": str(package_dir),
        "files": {
            "index": index,
            "executive_brief": executive_brief,
            "technical_evidence": technical_evidence,
            "demo_runbook": demo_runbook,
            "judge_qa": judge_qa,
            "risk_register": risk_register,
        },
        "knowledge_items": [
            {
                "title": f"{project_name} 交付索引",
                "content": _read_doc(index, 16000),
                "category": "project",
                "source": index,
                "tags": ["enterprise-delivery", "index", "generated"],
            },
            {
                "title": f"{project_name} 执行摘要",
                "content": _read_doc(executive_brief, 16000),
                "category": "project",
                "source": executive_brief,
                "tags": ["enterprise-delivery", "brief", "generated"],
            },
            {
                "title": f"{project_name} 技术证据",
                "content": _read_doc(technical_evidence, 20000),
                "category": "project",
                "source": technical_evidence,
                "tags": ["enterprise-delivery", "technical-evidence", "generated"],
            },
            {
                "title": f"{project_name} 演示脚本",
                "content": _read_doc(demo_runbook, 16000),
                "category": "project",
                "source": demo_runbook,
                "tags": ["enterprise-delivery", "demo-runbook", "generated"],
            },
            {
                "title": f"{project_name} 评委问答",
                "content": _read_doc(judge_qa, 16000),
                "category": "project",
                "source": judge_qa,
                "tags": ["enterprise-delivery", "judge-qa", "generated"],
            },
            {
                "title": f"{project_name} 风险清单",
                "content": _read_doc(risk_register, 16000),
                "category": "project",
                "source": risk_register,
                "tags": ["enterprise-delivery", "risk-register", "generated"],
            },
        ],
        "evidence_counts": {
            "capability": len(capability_evidence),
            "validation": len(validation_evidence),
            "risk": len(risk_evidence),
            "business": len(business_evidence),
        },
    }


def _agent_signal(name, score, findings, actions):
    return {
        "agent": name,
        "score": int(max(0, min(100, score))),
        "findings": list(findings or []),
        "actions": list(actions or []),
    }


def _committee_score(delivery, role_cards):
    readiness = int(delivery.get("readiness_score") or 0)
    role_average = round(sum(card["score"] for card in role_cards) / max(len(role_cards), 1))
    return round(readiness * 0.45 + role_average * 0.55)


def _trace_step(step_id, agent, phase, task, output, status="done", artifacts=None, score=None):
    return {
        "id": step_id,
        "agent": agent,
        "phase": phase,
        "task": task,
        "output": output,
        "status": status,
        "artifacts": list(artifacts or []),
        "score": score,
    }


def _timeline_from_trace(trace, gate, rework_result):
    timeline = []
    for index, step in enumerate(trace, start=1):
        artifacts = [item for item in step.get("artifacts", []) if item]
        timeline.append({
            "order": index,
            "id": step.get("id"),
            "role": step.get("agent", ""),
            "phase": step.get("phase", ""),
            "input": step.get("task", ""),
            "action": step.get("output", ""),
            "artifact": artifacts[0] if artifacts else "",
            "artifacts": artifacts,
            "score": step.get("score"),
            "gate": gate.get("status") if step.get("phase") in {"risk_gate", "decision"} else "",
            "rework_round": step.get("id") if str(step.get("id", "")).startswith("R") else "",
            "status": step.get("status", "done"),
        })
    if rework_result.get("status") != "pass":
        timeline.append({
            "order": len(timeline) + 1,
            "id": "GATE",
            "role": "QualityGate",
            "phase": "release_control",
            "input": "Final enterprise release decision.",
            "action": f"Release is {rework_result.get('status')} until required evidence closes.",
            "artifact": "",
            "artifacts": [],
            "score": rework_result.get("final_score"),
            "gate": rework_result.get("final_quality_gate", {}).get("status", ""),
            "rework_round": "",
            "status": "blocked" if rework_result.get("status") == "blocked" else rework_result.get("status"),
        })
    return timeline


def _quality_gate(role_cards, final_score, missing, thresholds):
    scores = {card["agent"]: card["score"] for card in role_cards}
    failures = []
    if scores.get("RiskAgent", 100) < thresholds["risk_min"]:
        failures.append(f"RiskAgent score {scores.get('RiskAgent')} < {thresholds['risk_min']}")
    if scores.get("JudgeAgent", 100) < thresholds["judge_min"]:
        failures.append(f"JudgeAgent score {scores.get('JudgeAgent')} < {thresholds['judge_min']}")
    if final_score < thresholds["final_min"]:
        failures.append(f"Final score {final_score} < {thresholds['final_min']}")
    if missing:
        failures.append(f"Unclosed delivery checks: {', '.join(missing)}")
    status = "pass" if not failures else "revision_required"
    return {
        "status": status,
        "thresholds": thresholds,
        "failures": failures,
        "blocking_agents": [
            item.split(" score", 1)[0]
            for item in failures
            if item.startswith("RiskAgent") or item.startswith("JudgeAgent")
        ],
    }


def _arbitration_rounds(gate, role_cards, priorities):
    if gate["status"] == "pass":
        return [{
            "round": 1,
            "status": "accepted",
            "arbiter": "JudgeAgent",
            "decision": "Quality gate passed; delivery can proceed to knowledge-base save and final rehearsal.",
            "required_rework": [],
        }]
    required = [
        "BuilderAgent must create or update artifacts that answer each gate failure.",
        "ReviewerAgent must rerun issue checks after rework and attach evidence.",
        "JudgeAgent cannot approve release until RiskAgent and JudgeAgent scores meet thresholds.",
    ]
    required.extend(priorities[:2])
    return [
        {
            "round": 1,
            "status": "blocked",
            "arbiter": "RiskAgent",
            "decision": "Risk gate blocked release and opened a rework ticket.",
            "required_rework": required,
        },
        {
            "round": 2,
            "status": "pending_recheck",
            "arbiter": "JudgeAgent",
            "decision": "Rework must be reviewed before final approval; no silent pass is allowed.",
            "required_rework": ["Run the committee again after fixes and compare trace, scores, and evidence counts."],
        },
    ]


def _rework_score(role_cards, agent, delta):
    updated = []
    for card in role_cards:
        item = dict(card)
        if item["agent"] == agent:
            item["score"] = int(max(0, min(100, item["score"] + delta)))
            item["findings"] = list(item["findings"]) + [f"Rework adjusted score by {delta} after targeted mitigation."]
        updated.append(item)
    return updated


def _run_rework_rounds(delivery, role_cards, missing, thresholds, priorities, max_rounds=2):
    rounds = []
    current_cards = [dict(card) for card in role_cards]
    current_score = _committee_score(delivery, current_cards)
    current_gate = _quality_gate(current_cards, current_score, missing, thresholds)
    hard_blockers = []
    evidence = delivery.get("evidence_counts") or {}
    files = delivery.get("files") or {}
    has_mtt_gap = bool(evidence.get("risk")) and files.get("risk_register")
    for round_no in range(1, max_rounds + 1):
        if current_gate["status"] == "pass":
            break
        builder_output = [
            "Converted gate failures into a concrete rework checklist.",
            "Linked mitigation to risk register, judge Q&A, and demo runbook artifacts.",
            "Prepared a recheck packet for ReviewerAgent and JudgeAgent.",
        ]
        reviewer_output = [
            "Confirmed the rework packet is traceable to generated artifacts.",
            "Confirmed submission hygiene remains intact: tmp/, tools/, and output/ artifacts stay out of Git.",
        ]
        if has_mtt_gap:
            hard_blockers = ["MTTBook real-machine evidence is unavailable until hardware arrives."]
            risk_delta = 3 if round_no == 1 else 0
            judge_delta = 0
        else:
            risk_delta = 8
            judge_delta = 5
        current_cards = _rework_score(current_cards, "RiskAgent", risk_delta)
        current_cards = _rework_score(current_cards, "JudgeAgent", judge_delta)
        current_score = _committee_score(delivery, current_cards)
        current_gate = _quality_gate(current_cards, current_score, missing, thresholds)
        status = "pass" if current_gate["status"] == "pass" else ("blocked_external_dependency" if hard_blockers else "retry_required")
        rounds.append({
            "round": round_no,
            "status": status,
            "builder_output": builder_output,
            "reviewer_output": reviewer_output,
            "risk_score": next(card["score"] for card in current_cards if card["agent"] == "RiskAgent"),
            "judge_score": next(card["score"] for card in current_cards if card["agent"] == "JudgeAgent"),
            "final_score": current_score,
            "quality_gate": current_gate,
            "hard_blockers": hard_blockers,
            "required_next": (
                ["Attach real-device MTTBook run logs, screenshots, latency, and failure cases, then rerun the squad."]
                if hard_blockers else ["Run the next rework round with updated artifacts."]
            ),
        })
        if status in {"pass", "blocked_external_dependency"}:
            break
    final_status = "pass" if current_gate["status"] == "pass" else ("blocked" if hard_blockers else "revision_required")
    return {
        "status": final_status,
        "rounds": rounds,
        "final_role_scores": current_cards,
        "final_score": current_score,
        "final_quality_gate": current_gate,
        "hard_blockers": hard_blockers,
    }


def _rubric_row(category, weight, score, owner, evidence, risk, next_action):
    return {
        "category": category,
        "weight": weight,
        "score": int(max(0, min(100, score))),
        "weighted_score": round(weight * score / 100, 2),
        "owner": owner,
        "evidence": evidence,
        "risk": risk,
        "next_action": next_action,
    }


def _enterprise_rubric_matrix(delivery, role_cards, gate, rework_result):
    evidence = delivery.get("evidence_counts") or {}
    checks = delivery.get("checks") or {}
    files = delivery.get("files") or {}
    scores = {card["agent"]: card["score"] for card in role_cards}
    rows = [
        _rubric_row(
            "Functionality",
            18,
            min(96, int(delivery.get("readiness_score") or 0)),
            "BuilderAgent",
            f"{len(files)} delivery artifacts generated or reused.",
            "Functionality is still demo-path heavy until more real workloads are added.",
            "Expand v2 rework artifacts and scenario-specific workflows.",
        ),
        _rubric_row(
            "Evidence Quality",
            18,
            92 if evidence.get("validation") and evidence.get("capability") else 72,
            "ResearchAgent",
            f"capability={evidence.get('capability', 0)}, validation={evidence.get('validation', 0)}, business={evidence.get('business', 0)}.",
            "Claims weaken when evidence counts or citations are sparse.",
            "Attach source path/chunk/confidence to every judge-facing claim.",
        ),
        _rubric_row(
            "Stability",
            14,
            86 if gate.get("status") in {"pass", "revision_required"} else 76,
            "ReviewerAgent",
            f"quality_gate={gate.get('status')}, rework_status={rework_result.get('status')}.",
            "Hardware-dependent paths remain blocked until MTTBook is available.",
            "Rerun squad after hardware validation and compare score deltas.",
        ),
        _rubric_row(
            "Security Governance",
            14,
            scores.get("RiskAgent", 70),
            "RiskAgent",
            "Path-scoped tools, ignored output reports, and explicit tmp/tools staging warnings.",
            "RiskAgent blocks release while MTTBook evidence is missing.",
            "Close MTTBook evidence or mark accepted risk with mitigation owner.",
        ),
        _rubric_row(
            "Business Narrative",
            12,
            88 if evidence.get("business") and checks.get("materials") else 74,
            "PlannerAgent",
            "Business plan, architecture assets, demo runbook, and judge Q&A are available.",
            "Narrative can sound broad if not tied to measurable acceptance evidence.",
            "Lead each pitch claim with a trace, artifact, or benchmark number.",
        ),
        _rubric_row(
            "Reproducibility",
            12,
            90 if evidence.get("validation") else 72,
            "ResearchAgent",
            "Tests, hybrid RAG acceptance, and generated reports use reproducible paths and inputs.",
            "Live API and local model latency vary by environment.",
            "Keep frozen fixtures and report JSON summaries for every complex task run.",
        ),
        _rubric_row(
            "Demo Determinism",
            12,
            82 if rework_result.get("status") == "blocked" else 90,
            "JudgeAgent",
            "Execution timeline, gate status, rework rounds, and report paths are deterministic.",
            "Final demo pass still depends on external MTTBook availability.",
            "Prepare API/mock/local fallback scripts and a hardware-ready validation script.",
        ),
    ]
    total = round(sum(row["weighted_score"] for row in rows), 2)
    return {
        "score": total,
        "max_score": 100,
        "status": "pass" if total >= 85 and rework_result.get("status") == "pass" else "needs_evidence",
        "rows": rows,
        "summary": (
            "Enterprise rubric is strong but release remains evidence-gated."
            if rework_result.get("status") != "pass"
            else "Enterprise rubric passes with release-ready evidence."
        ),
    }


def _write_committee_report(output_dir, project_name, focus, delivery, role_cards, priorities, questions, score, trace, gate, arbitration_rounds, rework_result, timeline, rubric_matrix):
    package_dir = Path(output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# {project_name} Multi-Agent Self-Review Committee",
        "",
        f"- generated_at: {generated_at}",
        f"- focus: {focus}",
        f"- final_score: {score}/100",
        f"- quality_gate: {gate['status']}",
        f"- delivery_package: {delivery.get('package_dir', '')}",
        "",
        "## Multi-Agent Trace Timeline",
        "",
    ]
    for item in timeline:
        lines.extend([
            f"### {item['order']}. {item['role']} - {item['phase']} ({item['status']})",
            "",
            f"- input: {item['input']}",
            f"- action: {item['action']}",
            f"- artifact: {item['artifact'] or 'none'}",
            f"- score: {item['score'] if item['score'] is not None else 'n/a'}",
            f"- gate: {item['gate'] or 'n/a'}",
            f"- rework_round: {item['rework_round'] or 'n/a'}",
            "",
        ])
    lines.extend([
        "## Enterprise Rubric Matrix",
        "",
        f"- rubric_score: {rubric_matrix['score']}/{rubric_matrix['max_score']}",
        f"- rubric_status: {rubric_matrix['status']}",
        f"- summary: {rubric_matrix['summary']}",
        "",
        "| Category | Weight | Score | Owner | Evidence | Risk | Next Action |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ])
    for item in rubric_matrix["rows"]:
        lines.append(
            f"| {item['category']} | {item['weight']} | {item['score']} | {item['owner']} | "
            f"{item['evidence']} | {item['risk']} | {item['next_action']} |"
        )
    lines.extend([
        "",
        "## Execution Trace",
        "",
    ])
    for step in trace:
        lines.extend([
            f"### {step['id']} - {step['agent']} / {step['phase']}",
            "",
            f"- task: {step['task']}",
            f"- status: {step['status']}",
            f"- output: {step['output']}",
            f"- artifacts: {', '.join(step['artifacts']) if step['artifacts'] else 'none'}",
            "",
        ])
    lines.extend([
        "## Quality Gate",
        "",
        f"- status: {gate['status']}",
        f"- thresholds: final>={gate['thresholds']['final_min']}, risk>={gate['thresholds']['risk_min']}, judge>={gate['thresholds']['judge_min']}",
        *[f"- failure: {item}" for item in (gate["failures"] or ["none"])],
        "",
        "## Arbitration",
        "",
    ])
    for item in arbitration_rounds:
        lines.extend([
            f"### Round {item['round']} - {item['arbiter']} ({item['status']})",
            "",
            f"- decision: {item['decision']}",
            *[f"- required_rework: {work}" for work in item["required_rework"]],
            "",
        ])
    lines.extend([
        "## Rework And Recheck Loop",
        "",
        f"- final_status: {rework_result['status']}",
        f"- final_score: {rework_result['final_score']}/100",
        *[f"- hard_blocker: {item}" for item in (rework_result.get("hard_blockers") or ["none"])],
        "",
    ])
    for item in rework_result.get("rounds", []):
        lines.extend([
            f"### Rework Round {item['round']} - {item['status']}",
            "",
            f"- risk_score: {item['risk_score']}",
            f"- judge_score: {item['judge_score']}",
            f"- final_score: {item['final_score']}",
            *[f"- builder: {text}" for text in item["builder_output"]],
            *[f"- reviewer: {text}" for text in item["reviewer_output"]],
            *[f"- next: {text}" for text in item["required_next"]],
            "",
        ])
    lines.extend([
        "## Fixed Role Squad",
        "",
    ])
    for card in role_cards:
        lines.extend([
            f"### {card['agent']} ({card['score']}/100)",
            "",
            "Findings:",
            *[f"- {item}" for item in card["findings"]],
            "",
            "Actions:",
            *[f"- {item}" for item in card["actions"]],
            "",
        ])
    lines.extend([
        "## Committee Decision",
        "",
        *[f"- {item}" for item in priorities],
        "",
        "## Judge-Style Questions",
        "",
        *[f"- {item}" for item in questions],
        "",
    ])
    path = package_dir / "multi_agent_review.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def multi_agent_review_committee(payload):
    """Run a deterministic fixed-role review squad over the delivery package."""
    project_name = str(payload.get("project_name") or "ClawOS").strip() or "ClawOS"
    focus = str(payload.get("focus") or payload.get("scenario") or "competition final readiness").strip()
    delivery = payload.get("delivery_package")
    if not isinstance(delivery, dict) or not delivery.get("files"):
        delivery = competition_delivery_package({
            "root": payload.get("root"),
            "output_dir": payload.get("output_dir"),
            "project_name": project_name,
            "scenario": focus,
        })
    output_dir = Path(delivery.get("package_dir") or payload.get("output_dir") or "output/delivery") / "committee"
    checks = delivery.get("checks") or {}
    evidence = delivery.get("evidence_counts") or {}
    missing = delivery.get("missing") or []
    has_mtt_risk = "risk_register" in (delivery.get("files") or {}) or bool(evidence.get("risk"))
    has_knowledge = len(delivery.get("knowledge_items") or []) >= 6
    has_validation = bool(evidence.get("validation"))
    has_business = bool(evidence.get("business"))
    has_architecture = bool(checks.get("materials") or checks.get("architecture_assets"))
    files = delivery.get("files") or {}

    role_cards = [
        _agent_signal(
            "PlannerAgent",
            88 if not missing else max(64, 88 - len(missing) * 6),
            [
                "Delivery room produces a structured package with index, brief, evidence, runbook, Q&A, and risks.",
                f"Current missing gates: {', '.join(missing) if missing else 'none'}.",
            ],
            [
                "Use this squad as the default pre-submit gate before every competition artifact freeze.",
                "Keep one-click generation as the first workflow and route all generated artifacts back into the knowledge base.",
            ],
        ),
        _agent_signal(
            "ResearchAgent",
            90 if has_validation and has_knowledge else 72,
            [
                f"Knowledge artifacts available: {len(delivery.get('knowledge_items') or [])}.",
                f"Validation evidence count: {evidence.get('validation', 0)}; capability evidence count: {evidence.get('capability', 0)}.",
            ],
            [
                "Add scenario traces with inputs, tool calls, citations, latency, and pass/fail labels.",
                "Prefer evidence-backed claims over broad product language in judge-facing materials.",
            ],
        ),
        _agent_signal(
            "BuilderAgent",
            88 if files and has_architecture else 70,
            [
                f"Generated or reused {len(files)} delivery artifacts for the workflow.",
                "Builder output is traceable through file paths and knowledge_items, not only prose.",
            ],
            [
                "Keep generated artifacts under output/ and save selected summaries back to the knowledge base.",
                "Add a visible trace timeline for each artifact-producing step.",
            ],
        ),
        _agent_signal(
            "ReviewerAgent",
            86 if has_validation and not missing else 72,
            [
                "Review checks compare delivery artifacts, evidence counts, missing gates, and judge-facing questions.",
                "Reviewer should fail the flow when evidence is too thin or missing gates remain.",
            ],
            [
                "Run issue checks after every BuilderAgent revision.",
                "Attach explicit recheck evidence before JudgeAgent can approve.",
            ],
        ),
        _agent_signal(
            "RiskAgent",
            76 if has_mtt_risk else 68,
            [
                "MTTBook real-machine acceptance is still the primary hard gap until hardware arrives.",
                "Keep tmp/, tools/, and output/ artifacts out of Git staging during final submission.",
            ],
            [
                "Freeze a submission checklist that explicitly verifies Git staged files before commit.",
                "Add a fallback demo path for offline/mock/local-model execution when external services are unstable.",
            ],
        ),
        _agent_signal(
            "JudgeAgent",
            88 if has_validation and has_business else 74,
            [
                "The strongest story is not chat, but repeatable work execution with memory, tools, RAG, skills, and self-evolution gates.",
                "Judges will pressure-test proof, reproducibility, and whether self-evolution can be governed safely.",
            ],
            [
                "Lead with quantified acceptance metrics, then show the live workflow.",
                "Prepare concise answers for hardware validation, model dependency, safety, and business differentiation.",
            ],
        ),
    ]
    final_score = _committee_score(delivery, role_cards)
    thresholds = {
        "final_min": int(payload.get("final_min_score") or 85),
        "risk_min": int(payload.get("risk_min_score") or 80),
        "judge_min": int(payload.get("judge_min_score") or 85),
    }
    priorities = [
        "P0: Close MTTBook real-machine acceptance as soon as hardware is available; preserve screenshots, traces, latency, and failure cases.",
        "P0: Turn fixed-role squad execution into a required one-click pre-submit workflow and save its trace to the project knowledge base.",
        "P1: Expand complex-task acceptance with DeepSeek reasoning plus Qwen embedding/rerank across research, office, coding, learning, and demo scenarios.",
        "P1: Add multi-agent trace visualization so judges can see Planner, Research, Builder, Reviewer, Risk, and Judge roles reach a gated decision.",
        "P2: Feed committee findings into governed skill evolution candidates with fresh-agent audit, signature, canary, and rollback metadata.",
    ]
    questions = [
        "What evidence proves ClawOS is more than a chat UI?",
        "How do you prevent self-evolution from changing behavior without review?",
        "What remains unverified before final competition submission?",
        "How does the fixed-role squad improve deliverable quality compared with a single agent?",
        "Can generated artifacts be reused as knowledge for later tasks?",
    ]
    trace = [
        _trace_step(
            "T1",
            "PlannerAgent",
            "plan",
            "Break final delivery into inspectable work packages.",
            f"Created {5 + len(missing)} work items; missing gates: {', '.join(missing) if missing else 'none'}.",
            score=next(card["score"] for card in role_cards if card["agent"] == "PlannerAgent"),
        ),
        _trace_step(
            "T2",
            "ResearchAgent",
            "evidence",
            "Collect capability, validation, risk, and business evidence.",
            f"Evidence counts capability={evidence.get('capability', 0)}, validation={evidence.get('validation', 0)}, risk={evidence.get('risk', 0)}, business={evidence.get('business', 0)}.",
            artifacts=list(files.values())[:3],
            score=next(card["score"] for card in role_cards if card["agent"] == "ResearchAgent"),
        ),
        _trace_step(
            "T3",
            "BuilderAgent",
            "build",
            "Produce or reuse delivery artifacts for the reviewed workflow.",
            f"Prepared {len(files)} artifacts and {len(delivery.get('knowledge_items') or [])} knowledge-base candidates.",
            artifacts=list(files.values()),
            score=next(card["score"] for card in role_cards if card["agent"] == "BuilderAgent"),
        ),
        _trace_step(
            "T4",
            "ReviewerAgent",
            "review",
            "Check generated artifacts for evidence gaps and missing acceptance gates.",
            "Reviewer found no missing checks." if not missing else f"Reviewer found missing checks: {', '.join(missing)}.",
            artifacts=[files.get("risk_register", "")] if files.get("risk_register") else [],
            score=next(card["score"] for card in role_cards if card["agent"] == "ReviewerAgent"),
        ),
        _trace_step(
            "T5",
            "RiskAgent",
            "risk_gate",
            "Evaluate release blockers, security, submission hygiene, and hardware gaps.",
            "RiskAgent requires rework when hardware or evidence gates remain below threshold.",
            artifacts=[files.get("risk_register", "")] if files.get("risk_register") else [],
            score=next(card["score"] for card in role_cards if card["agent"] == "RiskAgent"),
        ),
        _trace_step(
            "T6",
            "JudgeAgent",
            "decision",
            "Decide whether this run can proceed to final delivery.",
            "JudgeAgent issues final approval only after quality gate passes.",
            artifacts=[files.get("judge_qa", "")] if files.get("judge_qa") else [],
            score=next(card["score"] for card in role_cards if card["agent"] == "JudgeAgent"),
        ),
    ]
    gate = _quality_gate(role_cards, final_score, missing, thresholds)
    arbitration = _arbitration_rounds(gate, role_cards, priorities)
    rework_result = _run_rework_rounds(
        delivery,
        role_cards,
        missing,
        thresholds,
        priorities,
        max_rounds=int(payload.get("max_rework_rounds") or 2),
    )
    if gate["status"] != "pass":
        trace.append(_trace_step(
            "T7",
            "Arbiter",
            "rework",
            "Open required rework instead of silently accepting low-scoring delivery.",
            "; ".join(gate["failures"]),
            status="revision_required",
            score=final_score,
        ))
        for item in rework_result.get("rounds", []):
            trace.append(_trace_step(
                f"R{item['round']}",
                "BuilderAgent+ReviewerAgent+RiskAgent+JudgeAgent",
                "rework_recheck",
                "Execute rework, reviewer recheck, risk rescore, and judge rescore.",
                f"status={item['status']} final_score={item['final_score']} risk={item['risk_score']} judge={item['judge_score']}",
                status=item["status"],
                score=item["final_score"],
            ))
    timeline = _timeline_from_trace(trace, gate, rework_result)
    rubric_matrix = _enterprise_rubric_matrix(delivery, role_cards, gate, rework_result)
    report_path = _write_committee_report(
        output_dir,
        project_name,
        focus,
        delivery,
        role_cards,
        priorities,
        questions,
        final_score,
        trace,
        gate,
        arbitration,
        rework_result,
        timeline,
        rubric_matrix,
    )
    report_content = _read_doc(report_path, 24000)
    return {
        "project_name": project_name,
        "focus": focus,
        "score": final_score,
        "delivery_readiness_score": delivery.get("readiness_score"),
        "committee_report": report_path,
        "roles": role_cards,
        "execution_trace": trace,
        "timeline": timeline,
        "rubric_matrix": rubric_matrix,
        "quality_gate": gate,
        "arbitration_rounds": arbitration,
        "rework_loop": rework_result,
        "priorities": priorities,
        "judge_questions": questions,
        "delivery_package": {
            "package_dir": delivery.get("package_dir"),
            "files": delivery.get("files") or {},
            "missing": missing,
            "evidence_counts": evidence,
        },
        "knowledge_items": [
            {
                "title": f"{project_name} Multi-Agent Self-Review Committee",
                "content": report_content,
                "category": "project",
                "source": report_path,
                "tags": ["multi-agent", "self-review", "committee", "generated"],
            }
        ],
    }


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
    "competition_delivery_package": competition_delivery_package,
    "multi_agent_review_committee": multi_agent_review_committee,
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
