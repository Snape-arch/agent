from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from memoryos.memory_store import MemoryStore
from services.answer_quality_service import AnswerQualityService, ClaimEvidenceAnswerValidator, wilson_interval


DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality_common_tasks_v1.json"


SEEDS = [
    ("coding_pytest", "coding", "测试失败后什么时候可以结束修复？", "当目标测试和回归测试都通过时，修复任务才可以结束。", "修复任务才可以结束"),
    ("coding_lint", "coding", "什么时候应修复 lint 警告？", "当警告来自本次修改的文件时，应在交付前修复 lint 警告。", "应在交付前修复 lint 警告"),
    ("coding_env", "coding", "缺少编译器时应如何归类？", "当所需编译器未安装时，应把失败归类为环境失败。", "应把失败归类为环境失败"),
    ("coding_scope", "coding", "何时允许修改仓库外文件？", "仅当用户明确授权并且目标路径通过边界检查时，才允许修改仓库外文件。", "才允许修改仓库外文件"),
    ("coding_retry", "coding", "修复尝试失败后下一步是什么？", "当一次修复没有改善诊断时，应重新评估假设再决定下一步。", "应重新评估假设再决定下一步"),
    ("research_citation", "research", "论文结论什么时候可以进入报告？", "当结论能够绑定原文页码或段落时，才可以作为有依据结论进入报告。", "才可以作为有依据结论进入报告"),
    ("research_limit", "research", "论文局限应如何记录？", "当作者明确描述适用边界时，应将条件和局限与结论一起记录。", "应将条件和局限与结论一起记录"),
    ("research_conflict", "research", "两篇论文数字冲突怎么办？", "当多个来源给出不同数字时，应建立冲突记录并等待审核。", "应建立冲突记录并等待审核"),
    ("research_table", "research", "表格数据如何引用？", "当答案使用表格数值时，引用必须指向对应表格和行列位置。", "引用必须指向对应表格和行列位置"),
    ("research_search", "research", "何时需要联网查论文？", "当用户要求最新研究或外部来源时，才应启动联网检索。", "才应启动联网检索"),
    ("office_docx", "office", "DOCX 修改何时算完成？", "当文档重新渲染且版式检查通过时，DOCX 修改才算完成。", "DOCX 修改才算完成"),
    ("office_formula", "office", "电子表格公式何时可信？", "当公式经过兼容引擎重算并产生缓存值时，结果才可交付。", "结果才可交付"),
    ("office_revision", "office", "修订模式下怎么保存删除？", "当文档启用修订跟踪时，删除内容应写成 OOXML 删除修订。", "删除内容应写成 OOXML 删除修订"),
    ("office_style", "office", "模板样式如何保护？", "当编辑只涉及正文时，未触及的样式和主题部件必须保持哈希不变。", "未触及的样式和主题部件必须保持哈希不变"),
    ("office_preview", "office", "生成文件后为什么要预览？", "当生成可视文档时，必须通过页面渲染检查布局和截断问题。", "必须通过页面渲染检查布局和截断问题"),
    ("memory_fact", "memory", "事实记忆何时可以写入？", "当事实有可追溯来源并通过审核时，才可以写入正式知识库。", "才可以写入正式知识库"),
    ("memory_pref", "memory", "用户偏好如何形成？", "仅当用户明确表达偏好时，才可以创建用户偏好候选。", "才可以创建用户偏好候选"),
    ("memory_secret", "memory", "包含密钥的记忆怎么办？", "当候选内容包含密钥或密码时，必须脱敏并阻止自动晋升。", "必须脱敏并阻止自动晋升"),
    ("memory_duplicate", "memory", "相同记忆重复出现怎么办？", "当候选与已有记忆高度重复时，应标记重复而不是再次写入。", "应标记重复而不是再次写入"),
    ("memory_failure", "memory", "失败经验什么时候值得保存？", "当失败原因已定位且修复结果得到验证时，才可以保存失败经验。", "才可以保存失败经验"),
    ("search_stable", "search", "稳定常识要联网吗？", "当本地证据已经足够回答稳定事实时，不应继续联网搜索。", "不应继续联网搜索"),
    ("search_fresh", "search", "最新价格是否需要搜索？", "当问题依赖当前价格时，应检索最新且可验证的来源。", "应检索最新且可验证的来源"),
    ("search_highrisk", "search", "医疗结论应使用什么来源？", "当问题属于高风险医疗结论时，应优先使用权威和最新来源。", "应优先使用权威和最新来源"),
    ("search_community", "search", "经验问题需要社区来源吗？", "当问题询问实际使用体验时，应补充高质量社区来源。", "应补充高质量社区来源"),
    ("search_stop", "search", "搜索什么时候停止？", "当证据覆盖、来源质量和交叉验证达到要求时，应停止继续搜索。", "应停止继续搜索"),
    ("security_network", "security", "沙箱网络何时允许访问？", "仅当目标域名满足任务网络策略时，沙箱才可以发起外部请求。", "沙箱才可以发起外部请求"),
    ("security_delete", "security", "递归删除前要做什么？", "当执行递归删除时，必须先验证解析后的绝对目标路径。", "必须先验证解析后的绝对目标路径"),
    ("security_secret", "security", "日志什么时候需要脱敏？", "当日志字段可能包含凭证时，必须在持久化前完成脱敏。", "必须在持久化前完成脱敏"),
    ("security_approval", "security", "高风险命令怎么执行？", "仅当用户明确确认具体高风险操作时，系统才可以执行该命令。", "系统才可以执行该命令"),
    ("security_scope", "security", "多租户检索如何隔离？", "当执行知识检索时，必须在召回前应用所有者和工作区过滤。", "必须在召回前应用所有者和工作区过滤"),
    ("learning_quiz", "learning", "测验答案何时显示？", "当学习者提交答案后，系统才可以显示标准答案和解析。", "系统才可以显示标准答案和解析"),
    ("learning_mastery", "learning", "何时提高掌握度？", "当学习者提供可验证的正确作答证据时，才可以提高掌握度。", "才可以提高掌握度"),
    ("learning_review", "learning", "错题何时进入复习？", "当作答低于掌握门槛时，应创建错题并安排后续复习。", "应创建错题并安排后续复习"),
    ("learning_source", "learning", "学习笔记如何保留来源？", "当笔记由论文或资料生成时，应保留原始出处和定位信息。", "应保留原始出处和定位信息"),
    ("learning_feedback", "learning", "自动评分可当真人反馈吗？", "仅当反馈来自经同意的真实用户时，才可以计入独立真人反馈。", "才可以计入独立真人反馈"),
    ("operations_backup", "operations", "数据库迁移前要做什么？", "当迁移会修改生产数据库时，应先创建可验证的恢复备份。", "应先创建可验证的恢复备份"),
    ("operations_health", "operations", "索引健康如何判定？", "当有效记录数等于索引记录数且待处理事件为零时，索引才是一致状态。", "索引才是一致状态"),
    ("operations_retry", "operations", "后台任务什么时候重试？", "当失败被归类为可重试环境错误且未超过上限时，后台任务才应重试。", "后台任务才应重试"),
    ("operations_audit", "operations", "任务操作如何审计？", "当任务执行工具或改变状态时，应写入带任务标识的审计事件。", "应写入带任务标识的审计事件"),
    ("operations_finish", "operations", "任务什么时候可以标记完成？", "当所有明确验收条件通过时，任务才可以标记为完成。", "任务才可以标记为完成"),
]


def build_common_task_corpus() -> dict[str, Any]:
    records = []
    for index, (seed_id, domain, query, evidence_text, unconditional) in enumerate(SEEDS):
        citation = f"benchmark:{seed_id}"
        wrong = SEEDS[(index + 11) % len(SEEDS)]
        wrong_citation = f"benchmark:{wrong[0]}"
        evidence = [{"id": seed_id, "citation": citation, "text": evidence_text}]
        wrong_evidence = evidence + [{"id": wrong[0], "citation": wrong_citation, "text": wrong[3]}]
        split = "train" if index < 24 else ("dev" if index < 32 else "test")
        common = {"seed_id": seed_id, "domain": domain, "split": split, "query": query}
        variants = [
            ("supported", f"{evidence_text} [{citation}]", evidence, True, False, ""),
            ("wrong_citation", f"{evidence_text} [{wrong_citation}]", wrong_evidence, False, False, "citation_mismatch"),
            ("unsupported_expansion", f"{evidence_text} [{citation}]\n此外系统保证所有任务零延迟。 [{citation}]", evidence, False, False, "unsupported_expansion"),
            ("condition_omission", f"{unconditional} [{citation}]", evidence, False, False, "condition_omission"),
            ("missing_citation", evidence_text, evidence, False, False, "missing_citation"),
            ("correct_refusal", "现有知识库中没有足够证据支持这个结论。", [], True, True, ""),
        ]
        for variant, answer, case_evidence, expected_valid, must_refuse, expected_issue in variants:
            expected_relations = {
                "claims": [] if must_refuse else [{
                    "claim_contains": unconditional,
                    "supported_by": [citation],
                    "condition_required": True,
                }],
                "unsupported_claims": ["系统保证所有任务零延迟"] if variant == "unsupported_expansion" else [],
            }
            records.append({
                **common, "id": f"{seed_id}:{variant}", "variant": variant,
                "answer": answer, "expected_answer": evidence_text if not must_refuse else "",
                "evidence": case_evidence, "must_refuse": must_refuse,
                "expected_valid": expected_valid, "expected_issue": expected_issue,
                "expected_relations": expected_relations,
            })
    payload = {
        "name": "clawos-answer-quality-common-tasks-v1", "version": "1.0.0",
        "review_status": "maintainer_seeded_proxy",
        "truth_boundary": "Synthetic proxy interactions generated from maintainer-authored common-task facts; not real user feedback.",
        "records": records,
    }
    payload["corpus_digest"] = hashlib.sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def write_default_corpus(path: str | Path = DEFAULT_CORPUS) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_common_task_corpus(), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def run_answer_quality_benchmark(corpus_path: str | Path = DEFAULT_CORPUS) -> dict[str, Any]:
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    cases = corpus.get("records") or []
    if not 200 <= len(cases) <= 500:
        raise ValueError("answer quality corpus must contain 200-500 frozen cases")
    digest = hashlib.sha256(
        json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != corpus.get("corpus_digest"):
        raise ValueError("frozen corpus digest mismatch")

    correct = issue_correct = positives = negatives = positive_hits = negative_hits = 0
    split_metrics: dict[str, dict[str, int]] = {}
    failures = []
    with tempfile.TemporaryDirectory() as td:
        store = MemoryStore(str(Path(td) / "answer-quality.db"))
        quality = AnswerQualityService(store)
        for case in cases:
            validation = ClaimEvidenceAnswerValidator.validate(
                query=case["query"], answer=case["answer"], evidence=case["evidence"],
                expected_answer=case.get("expected_answer", ""), must_refuse=bool(case.get("must_refuse")),
            )
            predicted = bool(validation["valid"])
            expected = bool(case["expected_valid"])
            correct += int(predicted == expected)
            positives += int(expected)
            negatives += int(not expected)
            positive_hits += int(expected and predicted)
            negative_hits += int(not expected and not predicted)
            expected_issue = str(case.get("expected_issue") or "")
            issue_hit = not expected_issue or int(validation["issues"].get(expected_issue, 0)) > 0
            issue_correct += int(issue_hit)
            split = case["split"]
            bucket = split_metrics.setdefault(split, {"correct": 0, "total": 0})
            bucket["correct"] += int(predicted == expected)
            bucket["total"] += 1
            quality.record({
                **case, "origin": "benchmark_proxy", "consented": False,
                "dataset_split": split, "frozen": True, "corpus_version": corpus["version"],
                "metadata": {"case_id": case["id"], "expected_valid": expected, "expected_issue": expected_issue},
            })
            if predicted != expected or not issue_hit:
                failures.append({
                    "id": case["id"], "expected_valid": expected, "predicted_valid": predicted,
                    "expected_issue": expected_issue, "issues": validation["issues"],
                })
        intervals = {
            "classification_accuracy": wilson_interval(correct, len(cases)),
            "valid_answer_recall": wilson_interval(positive_hits, positives),
            "invalid_answer_rejection": wilson_interval(negative_hits, negatives),
            "issue_detection": wilson_interval(issue_correct, len(cases)),
        }
        metrics = {key: value["rate"] for key, value in intervals.items()}
        split_intervals = {
            key: wilson_interval(value["correct"], value["total"])
            for key, value in split_metrics.items()
        }
        metrics["split_accuracy"] = {key: value["rate"] for key, value in split_intervals.items()}
        thresholds = {
            "classification_accuracy": 0.95, "valid_answer_recall": 0.95,
            "invalid_answer_rejection": 0.95, "issue_detection": 0.95,
        }
        report = {
            "name": corpus["name"], "version": corpus["version"], "corpus_digest": digest,
            "case_count": len(cases), "fixed_test_count": sum(item["split"] == "test" for item in cases),
            "origin": "benchmark_proxy", "counts_as_real_user_feedback": False,
            "metrics": metrics, "confidence_intervals": intervals,
            "split_confidence_intervals": split_intervals, "thresholds": thresholds,
            "passed": all(metrics[key] >= value for key, value in thresholds.items()),
            "failures": failures, "feedback_stats": quality.stats(),
            "truth_boundary": corpus["truth_boundary"],
        }
        report["run_id"] = quality.save_run(report)
        return report
