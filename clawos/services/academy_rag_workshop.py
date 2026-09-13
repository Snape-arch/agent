"""Learner-scoped RAG teaching orchestration over a reproducible lab engine."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import academy_rag_engine as engine

DIAGNOSTIC = [
    dict(id="source", topic="rag", prompt="答案引用了一份已停用的规定，引用链接也能打开。你会怎样判断？",
         options=["链接可打开，所以答案可信", "还要核对版本和生效范围", "增加引用数量即可"], correct=1,
         feedback="引用可定位只是第一步，仍须检查版本与适用条件。", lesson="核验来源"),
    dict(id="missing", topic="embedding", prompt="资料只写了开放时间，用户问停车费用，检索却找到了开放时间。该怎么办？",
         options=["根据经验补一个价格", "复制开放时间作为答案", "说明证据不足，不能据此回答费用"], correct=2,
         feedback="主题相似不等于能回答问题；召回与答案可支持性必须分开检查。", lesson="识别证据不足"),
    dict(id="test", topic="evaluation", prompt="反复根据同一组 6 个问题调参数后全部通过，能宣布任意资料都可靠了吗？",
         options=["不能，需要新的迁移任务验证", "可以，已经是满分", "问题越少越容易说明能力"], correct=0,
         feedback="教学基准会被调参过程间接使用；通过不代表对新任务的泛化能力。", lesson="区分练习与迁移"),
]
TRANSFER = [
    dict(id="updated", prompt="新资料 A：旧课程每组 8 人（已停用）。B：现行课程每组 6 人。问现在每组人数，应选择？",
         options=["8 人，引用 A", "6 人，引用 B", "14 人，合并 A 与 B"], correct=1,
         feedback="应使用当前有效来源，不能把两个版本相加。"),
    dict(id="absence", prompt="新资料只说明机器人社团活动时间。问机器人维修费用，应选择？",
         options=["按活动时间推测费用", "将活动时间作为回答并引用", "资料不足，需要补充维修费用来源"], correct=2,
         feedback="有召回结果也可能没有答案证据。"),
    dict(id="negation", prompt="引用原文写着“打印服务不提供彩色打印”，回答却说“支持彩色打印”。引用 ID 有效，是否通过？",
         options=["通过，引用真实", "不通过，回答与原文矛盾", "只要回答包含彩色打印就通过"], correct=1,
         feedback="关键词和有效引用都不能代替检查否定关系。"),
]
GUIDES = {
    "retrieval": dict(title="先修复召回与切分", topic="embedding", hints=["检查正确事实是否完整出现在候选片段中。", "找到被切断的数量或单位，比较不同片段长度。", "用较长片段保留完整规则，再观察 Recall 和拒答是否同时变化。"]),
    "citation": dict(title="核对引用和版本", topic="rag", hints=["打开引用原文，核对它是否真的支持这个答案。", "比较旧版与现行器材规则；注意生效状态。", "启用现行资料过滤，并检查引用是否属于本次实际召回的片段。"]),
    "abstention": dict(title="处理没有答案的问题", topic="rag", hints=["看停车问题是否在任何资料中有明确答案。", "比较有答案与无答案问题的相似度分数。", "调整最低分阈值，使无关片段不被当作答案；同时检查正常问题是否误拒答。"]),
    "fact": dict(title="检查答案中的具体事实", topic="evaluation", hints=["核对数值、单位和否定词，不要只检查术语。", "对照原文和答案：遗漏来自切分还是生成？", "先修复证据完整性；模型生成时要求逐项引用并保留原文条件。"]),
}


class RagWorkshop:
    def __init__(self, store):
        self.store = store
        with store._conn() as conn:
            conn.executescript("""CREATE TABLE IF NOT EXISTS academy_rag_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
                CREATE INDEX IF NOT EXISTS academy_rag_learner_events ON academy_rag_events(learner_id,id);""")

    def _append(self, learner, kind, payload):
        with self.store._conn() as conn:
            cursor = conn.execute("INSERT INTO academy_rag_events(learner_id,kind,payload) VALUES (?,?,?)",
                                  (learner, kind, json.dumps(payload, ensure_ascii=False)))
            return cursor.lastrowid

    def _events(self, learner, kind="run"):
        with self.store._conn() as conn:
            return [dict(id=r["id"], kind=r["kind"], data=json.loads(r["payload"]), created_at=r["created_at"])
                    for r in conn.execute("SELECT * FROM academy_rag_events WHERE learner_id=? AND kind=? ORDER BY id DESC LIMIT 10", (learner, kind))]

    @staticmethod
    def questions(items):
        return [{k: v for k, v in item.items() if k not in ("correct", "feedback")} for item in items]

    def _find(self, learner, kind, event_id=None):
        with self.store._conn() as conn:
            query = "SELECT * FROM academy_rag_events WHERE learner_id=? AND kind=?"
            params = [learner, kind]
            if event_id is not None:
                query += " AND id=?"
                params.append(event_id)
            row = conn.execute(query + " ORDER BY id DESC LIMIT 1", params).fetchone()
            return dict(id=row["id"], kind=row["kind"], data=json.loads(row["payload"]), created_at=row["created_at"]) if row else None

    def state(self, learner="local-user"):
        events = self._events(learner)
        latest = lambda kind: self._find(learner, kind)
        return dict(version=engine.VERSION, documents=engine.DOCUMENTS, cases=[{k: c[k] for k in ("id", "query", "kind")} for c in engine.CASES],
                    diagnostic=self.questions(DIAGNOSTIC), transfer=self.questions(TRANSFER),
                    guides=GUIDES, default_config=engine.DEFAULT_CONFIG, diagnosis=latest("diagnosis"),
                    runs=[e for e in events if e["kind"] == "run"][:10], acceptance=latest("acceptance"), tutor=latest("tutor"),
                    code_url="/academy/code?workshop=rag", boundary="教学实验记录与正式知识库隔离；不自动写入掌握度。")

    def diagnose(self, answers, learner="local-user", transfer=False):
        questions = TRANSFER if transfer else DIAGNOSTIC
        if not isinstance(answers, dict) or set(answers) != {q["id"] for q in questions}:
            raise ValueError("请回答全部诊断题")
        rows = []
        for q in questions:
            choice = answers[q["id"]]
            if type(choice) is not int or not 0 <= choice < len(q["options"]):
                raise ValueError("诊断选项无效")
            rows.append(dict(id=q["id"], passed=choice == q["correct"], feedback=q["feedback"],
                             topic=q.get("topic", "rag"), choice=choice))
        result = dict(rows=rows, passed=sum(r["passed"] for r in rows), total=len(rows),
                      review_topics=list(dict.fromkeys(r["topic"] for r in rows if not r["passed"])))
        if not transfer:
            result["id"] = self._append(learner, "diagnosis", result)
        return result

    def record_run(self, result, learner="local-user"):
        result["digest"] = engine.digest(result)
        result["id"] = self._append(learner, "run", result)
        return result

    def tutor_context(self, run_id, learner="local-user"):
        if type(run_id) is not int:
            raise ValueError("请选择已保存的运行")
        run = self._find(learner, "run", run_id)
        if not run:
            raise ValueError("运行不存在或不属于当前学习者")
        return run["data"]

    def save_tutor_reply(self, run_id, question, answer, learner="local-user"):
        self.tutor_context(run_id, learner)
        payload = dict(run_id=run_id, question=question, answer=answer)
        payload["id"] = self._append(learner, "tutor", payload)
        return payload

    def run(self, config, learner="local-user"):
        return self.record_run(engine.run(config), learner)

    def accept(self, run_id, answers, learner="local-user"):
        if type(run_id) is not int:
            raise ValueError("请选择一次已保存的运行")
        run = self._find(learner, "run", run_id)
        if not run:
            raise ValueError("运行不存在或不属于当前学习者")
        if not self._find(learner, "diagnosis"):
            raise ValueError("请先完成入学诊断")
        result = self.diagnose(answers, learner, transfer=True)
        passed = run["data"]["passed"] == run["data"]["total"] and result["passed"] == result["total"]
        payload = dict(run_id=run_id, run_digest=run["data"]["digest"], transfer=result, passed=passed,
                       review_at=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat(),
                       boundary="通过的是固定教学任务和三个迁移选择题，不是对任意资料的能力认证。")
        payload["id"] = self._append(learner, "acceptance", payload)
        return payload

    def export(self, run_id, learner="local-user"):
        run = self._find(learner, "run", run_id)
        if not run:
            raise ValueError("运行不存在或不属于当前学习者")
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("rag_lab.py", Path(engine.__file__).read_text(encoding="utf-8"))
            archive.writestr("config.json", json.dumps(run["data"]["config"], ensure_ascii=False, indent=2))
            archive.writestr("run-report.json", json.dumps(run, ensure_ascii=False, indent=2))
            archive.writestr("README.md", "# RAG 教学实验\n\n运行：`python rag_lab.py --config config.json`\n\n仅需 Python 标准库；使用合成资料、字符二元组检索与摘录基线。\n模型模式报告保留原结果，本地脚本只重现摘录基线，不会调用模型。\n\n报告检查固定事实、来源与拒答，不能证明所有自由文本语义正确。\n请添加自己的新资料与独立测试集，再判断迁移效果。\n")
        return data.getvalue()
