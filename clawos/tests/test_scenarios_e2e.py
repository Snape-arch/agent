import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_tool(tool_runner, name, payload):
    tool_runner.input_data = payload
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        tool_runner.handlers[name]()
    return json.loads(output.getvalue())


class ScenarioEndToEndTests(unittest.TestCase):
    def test_office_meeting_workspace_creates_structured_minutes(self):
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            old_notes = tool_runner.NOTES_DIR
            tool_runner.NOTES_DIR = td
            try:
                result = run_tool(tool_runner, "meeting_template", {
                    "title": "Weekly Delivery Review",
                    "attendees": ["Alice", "Bob"],
                    "date": "2026-06-13",
                })
                content = Path(result["saved_to"]).read_text(encoding="utf-8")
            finally:
                tool_runner.NOTES_DIR = old_notes

        self.assertIn("## Decisions Made", content)
        self.assertIn("## Action Items", content)
        self.assertIn("Alice, Bob", content)

    def test_research_workspace_analyzes_bilingual_material(self):
        from scripts import tool_runner

        result = run_tool(tool_runner, "text_stats", {
            "text": "Agent memory improves task continuity. 长期记忆提升智能体任务连续性。"
        })

        self.assertGreater(result["characters"], 10)
        self.assertIn(result["language"], {"zh", "en", "mixed"})

    def test_learning_knowledge_is_retrievable_in_context(self):
        from memoryos.context_builder import ContextBuilder
        from memoryos.memory_store import MemoryStore
        from memoryos.services.vector_store import MemoryVectorStore

        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "memory.db")
            store = MemoryStore(db_path)
            store.upsert_memory(
                "project",
                "learning_goal",
                "Master retrieval augmented generation before July",
                category="learning",
                source="user_goal",
                confidence=0.9,
            )
            vectors = MemoryVectorStore(db_path)
            messages = ContextBuilder(store, vectors).build_messages(
                "learning-session",
                "What should I study before July?",
            )

        system_context = "\n".join(m["content"] for m in messages if m["role"] == "system")
        self.assertIn("retrieval augmented generation", system_context)

    def test_local_project_setup_and_code_collaboration_tools(self):
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            project = run_tool(tool_runner, "project_init", {
                "name": "delivery_demo",
                "type": "python",
                "root": td,
            })
            source = Path(project["path"]) / "src" / "main.py"
            source.write_text("# TODO: implement service\n", encoding="utf-8")
            stats = run_tool(tool_runner, "code_stats", {"path": project["path"]})
            todos = run_tool(tool_runner, "find_todos", {"path": project["path"]})
            readme_exists = (Path(project["path"]) / "README.md").exists()

        self.assertTrue(readme_exists)
        self.assertEqual(stats["by_language"]["Python"]["files"], 1)
        self.assertEqual(todos["count"], 1)

    def test_expanded_scenario_tools_cover_meeting_paper_exam_work_and_research(self):
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            meeting = run_tool(tool_runner, "meeting_action_items", {
                "title": "Launch Review",
                "participants": ["Alice", "Bob"],
                "transcript": "Alice decided to freeze the demo. Bob will finish tests tomorrow. Risk: API key setup may block rehearsal.",
                "output_path": str(Path(td) / "meeting.md"),
            })
            paper = run_tool(tool_runner, "paper_deep_read", {
                "title": "Agent Memory Study",
                "text": "The method uses a memory retrieval module. Experiments on task continuity improve results. Limitation: small dataset.",
            })
            exam = run_tool(tool_runner, "exam_practice_builder", {
                "topics": ["linear algebra", "probability"],
                "count": 4,
            })
            brief = run_tool(tool_runner, "work_brief_builder", {
                "title": "Weekly Brief",
                "context": "Goal: finish frontend polish. Risk: testing time is short. Deliver a clean demo.",
            })
            experiment = run_tool(tool_runner, "research_experiment_plan", {
                "question": "Does memory retrieval improve task completion?",
                "datasets": ["frozen benchmark"],
            })
            saved_meeting_exists = Path(meeting["saved_to"]).exists()

        self.assertTrue(saved_meeting_exists)
        self.assertGreaterEqual(len(meeting["action_items"]), 1)
        self.assertIn("method_evidence", paper)
        self.assertEqual(len(exam["questions"]), 4)
        self.assertIn("milestones", brief)
        self.assertIn("results.json", experiment["artifacts"])

    def test_competition_delivery_package_generates_enterprise_artifacts(self):
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "clawos").mkdir()
            (root / "架构图").mkdir()
            (root / "计划书和题目要求").mkdir()
            (root / "ClawOS_商业计划书.md").write_text(
                "ClawOS 面向科研、办公、教育和开发用户，具备商业模式和市场价值。\n",
                encoding="utf-8",
            )
            (root / "架构说明.txt").write_text(
                "MTClaw + MemoryOS + Reflection + RAG + Skill 自进化架构。\n",
                encoding="utf-8",
            )
            (root / "PROJECT_CONTEXT.md").write_text(
                "Verification: python -m unittest discover -s clawos\\tests: 174 tests OK. "
                "Known risk: MTTBook hardware validation remains deferred.\n",
                encoding="utf-8",
            )
            (root / "clawos" / "MTCLAW_INTEGRATION.md").write_text(
                "MTClaw Function Router and Tool History provide trace evidence.\n",
                encoding="utf-8",
            )
            (root / "架构图" / "architecture.png").write_bytes(b"fake")
            (root / "计划书和题目要求" / "plan.docx").write_bytes(b"fake")

            result = run_tool(tool_runner, "competition_delivery_package", {
                "root": str(root),
                "output_dir": str(root / "out"),
                "project_name": "ClawOS",
                "scenario": "competition final",
            })
            files = result["files"]
            index = Path(files["index"]).read_text(encoding="utf-8")
            qa = Path(files["judge_qa"]).read_text(encoding="utf-8")
            executive_brief_exists = Path(files["executive_brief"]).exists()

        self.assertGreaterEqual(result["readiness_score"], 80)
        self.assertTrue(executive_brief_exists)
        self.assertEqual(len(result["knowledge_items"]), 6)
        self.assertTrue(all(item["category"] == "project" for item in result["knowledge_items"]))
        self.assertIn("score=", index)
        self.assertIn("自进化", qa)

    def test_multi_agent_review_committee_generates_role_report(self):
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "clawos").mkdir()
            (root / "架构图").mkdir()
            (root / "计划书和题目要求").mkdir()
            (root / "ClawOS_商业计划书.md").write_text(
                "ClawOS has a commercial plan for research, office, education, and developer users.\n",
                encoding="utf-8",
            )
            (root / "架构说明.txt").write_text(
                "MTClaw, MemoryOS, Reflection, RAG, Skill, and self-evolution form the architecture.\n",
                encoding="utf-8",
            )
            (root / "PROJECT_CONTEXT.md").write_text(
                "Verification: 174 tests OK. Risk: MTTBook hardware validation remains deferred.\n",
                encoding="utf-8",
            )
            (root / "clawos" / "MTCLAW_INTEGRATION.md").write_text(
                "MTClaw Function Router and Tool History are execution evidence.\n",
                encoding="utf-8",
            )
            (root / "架构图" / "architecture.png").write_bytes(b"fake")
            (root / "计划书和题目要求" / "plan.docx").write_bytes(b"fake")

            result = run_tool(tool_runner, "multi_agent_review_committee", {
                "root": str(root),
                "output_dir": str(root / "out"),
                "project_name": "ClawOS",
                "focus": "final submission",
            })
            report = Path(result["committee_report"]).read_text(encoding="utf-8")

        self.assertGreaterEqual(result["score"], 70)
        self.assertEqual(len(result["roles"]), 5)
        self.assertEqual(result["roles"][0]["agent"], "PlannerAgent")
        self.assertIn("RiskAgent", report)
        self.assertIn("JudgeAgent", report)
        self.assertEqual(len(result["knowledge_items"]), 1)
        self.assertIn("P0:", "\n".join(result["priorities"]))


if __name__ == "__main__":
    unittest.main()
