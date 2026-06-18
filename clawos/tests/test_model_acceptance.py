import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelAcceptanceScriptTests(unittest.TestCase):
    def test_model_acceptance_script_runs_with_mock_provider(self):
        script = ROOT / "scripts" / "evaluate_model_acceptance.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--provider",
                "mock",
                "--mock-response",
                "PASS: meeting tool evidence is sufficient.",
                "--limit",
                "2",
                "--json",
            ],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["provider"], "mock")
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["benchmark"]["case_count"], 2)
        self.assertEqual(payload["evaluation"]["cases"], 2)
        self.assertEqual(payload["evaluation"]["score_rate"], 1.0)
        self.assertNotIn("api_key", result.stdout.lower())
        self.assertNotIn("sk-", result.stdout.lower())

    def test_model_acceptance_text_output_includes_counts(self):
        script = ROOT / "scripts" / "evaluate_model_acceptance.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--provider",
                "mock",
                "--mock-response",
                "PASS: meeting tool evidence is sufficient.",
                "--limit",
                "2",
            ],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Model acceptance: ok=True", result.stdout)
        self.assertIn("passed_count=2", result.stdout)
        self.assertIn("failed_count=0", result.stdout)
        self.assertNotIn("api_key", result.stdout.lower())
        self.assertNotIn("sk-", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
