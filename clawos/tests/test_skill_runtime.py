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


if __name__ == "__main__":
    unittest.main()
