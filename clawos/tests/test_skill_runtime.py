import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SkillRuntimeTests(unittest.TestCase):
    def test_registered_skills_reference_known_tools(self):
        from skills.skill_registry import list_skills, validate_skill_steps

        for skill in list_skills():
            validation = validate_skill_steps(skill["steps"])
            self.assertEqual(validation["errors"], [], skill["name"])

    def test_skill_supports_parameters_and_cross_step_references(self):
        from skills.skill_registry import execute_skill

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "demo.py"
            source.write_text("# TODO: add implementation\nprint('ok')\n", encoding="utf-8")
            result = execute_skill("dev_health_check", {"path": td})

        self.assertTrue(result["ok"])
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["outputs"][0]["result"]["path"], td)
        self.assertEqual(result["outputs"][2]["result"]["total_files"], 1)

    def test_skill_stops_when_required_parameter_is_missing(self):
        from skills.skill_registry import execute_skill

        result = execute_skill("research_code_analyzer", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], 0)
        self.assertIn("$param.path", result["error"])

    def test_skill_execute_api_contract_and_plan_runtime(self):
        from skills.skill_registry import execute_skill_definition, get_skill

        server_source = (ROOT / "clawos_server.py").read_text(encoding="utf-8")
        self.assertIn('@app.post("/api/skills/execute")', server_source)
        self.assertIn('plan_only = bool(data.get("plan_only", True))', server_source)
        self.assertIn('execute_skill_definition(skill, params=params, plan_only=True)', server_source)

        skill = get_skill("dev_health_check")
        result = execute_skill_definition(skill, {"path": str(ROOT)}, plan_only=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["outputs"][0]["result"]["planned"], True)
    def test_generated_replay_script_uses_shared_runtime(self):
        from skills.skill_registry import get_skill

        skill = get_skill("dev_health_check")
        script = ROOT / "skills" / f"skill_{skill['name']}.py"
        content = script.read_text(encoding="utf-8")
        self.assertIn("from skill_registry import execute_skill", content)
        with tempfile.TemporaryDirectory() as td:
            Path(td, "demo.py").write_text("print('ok')\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script), json.dumps({"path": td})],
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])

    def test_enterprise_delivery_room_skill_generates_package(self):
        from skills.skill_registry import execute_skill_definition, get_skill

        skill = get_skill("clawos_enterprise_delivery_room")
        self.assertIsNotNone(skill)
        self.assertEqual(
            [step["tool"] for step in skill["steps"]],
            ["competition_delivery_package"],
        )

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
                "Verification: 174 tests OK. Risk: MTT AIBOOK validation is deferred.\n",
                encoding="utf-8",
            )
            (root / "clawos" / "MTCLAW_INTEGRATION.md").write_text(
                "MTClaw Function Router and Tool History are the execution evidence.\n",
                encoding="utf-8",
            )
            (root / "架构图" / "architecture.png").write_bytes(b"fake")
            (root / "计划书和题目要求" / "plan.docx").write_bytes(b"fake")
            params = {
                "root": str(root),
                "output_dir": str(root / "out"),
                "project_name": "ClawOS",
                "scenario": "competition delivery",
            }
            plan = execute_skill_definition(skill, params, plan_only=True)
            result = execute_skill_definition(skill, params, plan_only=False)
            package = result["outputs"][0]["result"]
            index_exists = Path(package["files"]["index"]).exists()

        self.assertTrue(plan["ok"])
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(package["readiness_score"], 80)
        self.assertTrue(index_exists)

    def test_self_review_committee_skill_runs_fixed_roles(self):
        from skills.skill_registry import execute_skill_definition, get_skill

        skill = get_skill("clawos_self_review_committee")
        self.assertIsNotNone(skill)
        self.assertEqual(
            [step["tool"] for step in skill["steps"]],
            ["multi_agent_review_committee"],
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "clawos").mkdir()
            (root / "架构图").mkdir()
            (root / "计划书和题目要求").mkdir()
            (root / "ClawOS_商业计划书.md").write_text(
                "Commercial plan for research, office, education, and developer users.\n",
                encoding="utf-8",
            )
            (root / "架构说明.txt").write_text(
                "MTClaw, MemoryOS, Reflection, RAG, Skill, and self-evolution architecture.\n",
                encoding="utf-8",
            )
            (root / "PROJECT_CONTEXT.md").write_text(
                "Verification: tests OK. Risk: MTTBook validation deferred.\n",
                encoding="utf-8",
            )
            (root / "clawos" / "MTCLAW_INTEGRATION.md").write_text(
                "MTClaw Function Router and Tool History are execution evidence.\n",
                encoding="utf-8",
            )
            (root / "架构图" / "architecture.png").write_bytes(b"fake")
            (root / "计划书和题目要求" / "plan.docx").write_bytes(b"fake")
            params = {
                "root": str(root),
                "output_dir": str(root / "out"),
                "project_name": "ClawOS",
                "focus": "competition final readiness",
            }
            plan = execute_skill_definition(skill, params, plan_only=True)
            result = execute_skill_definition(skill, params, plan_only=False)
            committee = result["outputs"][0]["result"]
            report_exists = Path(committee["committee_report"]).exists()
            first_rework = committee["rework_loop"]["rounds"][0]
            v2_paths = list(first_rework["v2_artifacts"].values())
            v2_files_exist = all(Path(path).exists() for path in v2_paths)

        self.assertTrue(plan["ok"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(committee["roles"]), 6)
        self.assertGreaterEqual(committee["score"], 70)
        self.assertIn("execution_trace", committee)
        self.assertIn("quality_gate", committee)
        self.assertIn("arbitration_rounds", committee)
        self.assertIn("disagreement_log", committee)
        self.assertIn("rework_loop", committee)
        self.assertIn("timeline", committee)
        self.assertIn("rubric_matrix", committee)
        self.assertIn(committee["rework_loop"]["status"], {"pass", "blocked", "revision_required"})
        self.assertIn("v2_artifacts", first_rework)
        self.assertIn("reviewer_diff", first_rework)
        self.assertIn("judge_decision", first_rework)
        self.assertTrue(v2_files_exist)
        self.assertGreaterEqual(len(committee["disagreement_log"]), 3)
        self.assertTrue(any(item["objector"] == "JudgeAgent" for item in committee["disagreement_log"]))
        self.assertGreaterEqual(len(committee["execution_trace"]), 8)
        self.assertGreaterEqual(len(committee["timeline"]), 8)
        self.assertEqual(len(committee["rubric_matrix"]["rows"]), 7)
        self.assertTrue(report_exists)


if __name__ == "__main__":
    unittest.main()


