import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SkillEvolutionTests(unittest.TestCase):
    def setUp(self):
        from skills import skill_registry

        self.registry = skill_registry
        self.old_skills_dir = skill_registry.SKILLS_DIR
        self.old_registry_file = skill_registry.REGISTRY_FILE
        self.old_functions_file = skill_registry.FUNCTIONS_FILE
        self.old_scripts_dir = skill_registry.SCRIPTS_DIR
        self.old_cache = skill_registry._skills_cache
        self.old_mtime = skill_registry._cache_mtime
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        skills_dir = root / "skills"
        skills_dir.mkdir()
        (root / "functions.jsonl").write_text(
            "\n".join([
                json.dumps({
                    "name": "time_now",
                    "description": "clock",
                    "parameters": {"type": "object", "properties": {}},
                }),
                json.dumps({
                    "name": "work_brief_builder",
                    "description": "work brief",
                    "parameters": {"type": "object", "properties": {}},
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        baseline = {
            "name": "daily_clock",
            "display_name": "Daily Clock",
            "description": "Show the time",
            "steps": [{"tool": "time_now", "args": {}}],
            "trigger_keywords": ["time"],
            "tags": ["utility"],
            "category": "general",
            "version": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "use_count": 0,
        }
        registry_file = skills_dir / "skill_registry.jsonl"
        registry_file.write_text(json.dumps(baseline) + "\n", encoding="utf-8")
        skill_registry.SKILLS_DIR = skills_dir
        skill_registry.REGISTRY_FILE = registry_file
        skill_registry.FUNCTIONS_FILE = root / "functions.jsonl"
        skill_registry.SCRIPTS_DIR = ROOT / "scripts"
        skill_registry._skills_cache = None
        skill_registry._cache_mtime = 0.0

        from memoryos.memory_store import MemoryStore
        from skills.skill_evolution import SkillEvolutionManager

        self.manager = SkillEvolutionManager(MemoryStore(str(root / "memory.db")))

    def tearDown(self):
        self.registry.SKILLS_DIR = self.old_skills_dir
        self.registry.REGISTRY_FILE = self.old_registry_file
        self.registry.FUNCTIONS_FILE = self.old_functions_file
        self.registry.SCRIPTS_DIR = self.old_scripts_dir
        self.registry._skills_cache = self.old_cache
        self.registry._cache_mtime = self.old_mtime
        self.temp.cleanup()

    def test_candidate_requires_frozen_evidence_before_promotion_and_can_rollback(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "display_name": "Daily Clock",
                "description": "Show time with a reusable plan",
                "steps": [{"tool": "time_now", "args": {}}],
                "trigger_keywords": ["time", "clock"],
            },
            change_reason="reflection card found weak matching",
            source_ref="reflection:17",
        )
        suite = self.manager.create_suite(
            "clock-regression-v1",
            "daily_clock",
            [{
                "name": "uses approved clock tool",
                "mode": "plan",
                "expected": {"ok": True, "step_count": 1, "tools": ["time_now"]},
            }],
        )
        with self.assertRaisesRegex(ValueError, "validated"):
            self.manager.promote(candidate["id"])

        run = self.manager.evaluate(candidate["id"], suite["id"])
        promotion = self.manager.promote(candidate["id"], actor="reviewer")
        active = self.registry.get_skill("daily_clock")
        rollback = self.manager.rollback(promotion["id"])
        restored = self.registry.get_skill("daily_clock")

        self.assertTrue(run["passed"])
        self.assertEqual(active["version"], 2)
        self.assertEqual(active["trigger_keywords"], ["time", "clock"])
        self.assertEqual(rollback["status"], "rolled_back")
        self.assertEqual(restored["version"], 1)
        self.assertEqual(restored["trigger_keywords"], ["time"])

    def test_failed_gate_rejects_candidate(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "steps": [{"tool": "time_now", "args": {}}],
                "description": "candidate",
            },
        )
        suite = self.manager.create_suite(
            "wrong-tool-sequence",
            "daily_clock",
            [{
                "mode": "plan",
                "expected": {"tools": ["text_stats"]},
            }],
        )
        run = self.manager.evaluate(candidate["id"], suite["id"])

        self.assertFalse(run["passed"])
        self.assertEqual(self.manager.list_versions("daily_clock")[0]["status"], "rejected")
        with self.assertRaisesRegex(ValueError, "validated"):
            self.manager.promote(candidate["id"])

    def test_candidate_execution_does_not_publish_or_increment_usage(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "steps": [{"tool": "time_now", "args": {}}],
                "description": "candidate",
            },
        )
        result = self.registry.execute_skill_definition(
            candidate["definition"], plan_only=True
        )
        active = self.registry.get_skill("daily_clock")

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(active["version"], 1)
        self.assertEqual(active["use_count"], 0)

    def test_frozen_suite_can_execute_candidate_without_publishing_it(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "steps": [{"tool": "time_now", "args": {}}],
                "description": "candidate",
            },
        )
        suite = self.manager.create_suite(
            "clock-execution-v1",
            "daily_clock",
            [{
                "name": "executes clock tool",
                "mode": "execute",
                "expected": {"ok": True, "step_count": 1, "tools": ["time_now"]},
                "max_latency_ms": 5000,
            }],
        )
        run = self.manager.evaluate(candidate["id"], suite["id"])
        active = self.registry.get_skill("daily_clock")

        self.assertTrue(run["passed"])
        self.assertEqual(run["case_results"][0]["result"]["mode"], "execute")
        self.assertEqual(active["version"], 1)
        self.assertEqual(active["use_count"], 0)

    def test_plan_mode_allows_symbolic_references_to_prior_steps(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "steps": [
                    {"tool": "time_now", "args": {}},
                    {"tool": "time_now", "args": {"prior_date": "$step_0.date"}},
                ],
                "description": "candidate",
            },
        )
        suite = self.manager.create_suite(
            "clock-plan-chain-v1",
            "daily_clock",
            [{
                "mode": "plan",
                "expected": {
                    "ok": True,
                    "step_count": 2,
                    "tools": ["time_now", "time_now"],
                },
            }],
        )

        run = self.manager.evaluate(candidate["id"], suite["id"])

        self.assertTrue(run["passed"])

    def test_review_inbox_supports_needs_changes_and_reopen(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "steps": [{"tool": "time_now", "args": {}}],
                "description": "candidate",
            },
        )

        inbox = self.manager.review_inbox()
        needs_changes = self.manager.review(
            candidate["id"], "needs_changes", reviewer="tester", notes="add examples"
        )
        reopened = self.manager.review(candidate["id"], "reopen", reviewer="tester")
        rejected = self.manager.review(candidate["id"], "reject", reviewer="tester")

        self.assertTrue(any(item["id"] == candidate["id"] for item in inbox))
        self.assertEqual(needs_changes["status"], "needs_changes")
        self.assertEqual(reopened["status"], "candidate")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.manager.review_inbox(status="rejected")[0]["review_events"][0]["action"], "reject")

    def test_signature_manifest_fresh_audit_and_canary(self):
        candidate = self.manager.propose(
            "daily_clock",
            {
                "steps": [{"tool": "time_now", "args": {}}],
                "description": "candidate",
            },
        )
        suite = self.manager.create_suite(
            "clock-canary-v1",
            "daily_clock",
            [{
                "mode": "plan",
                "expected": {"ok": True, "step_count": 1, "tools": ["time_now"]},
            }],
        )
        run = self.manager.evaluate(candidate["id"], suite["id"])
        manifest = self.manager.dependency_manifest(candidate["id"])
        signature = self.manager.sign_version(candidate["id"], signer="tester", secret="secret")
        audit = self.manager.fresh_agent_audit(candidate["id"], suite["id"])
        canary = self.manager.start_canary(candidate["id"], percent=5, actor="tester")
        promotion = self.manager.promote(candidate["id"], actor="tester")

        self.assertTrue(run["passed"])
        self.assertEqual(manifest["tools"], ["time_now"])
        self.assertEqual(signature["signer"], "tester")
        self.assertTrue(audit["passed"])
        self.assertEqual(canary["percent"], 5.0)
        self.assertEqual(promotion["to_version_id"], candidate["id"])

    def test_new_scenario_skill_can_complete_evolution_loop(self):
        candidate = self.manager.propose(
            "delivery_brief",
            {
                "display_name": "Delivery Brief",
                "description": "Create a structured work delivery brief",
                "steps": [{
                    "tool": "work_brief_builder",
                    "args": {
                        "title": "$param.title",
                        "context": "$param.context",
                    },
                }],
                "trigger_keywords": ["delivery brief", "工作汇报"],
                "category": "office",
            },
        )
        suite = self.manager.create_suite(
            "delivery-brief-v1",
            "delivery_brief",
            [{
                "name": "creates work brief from context",
                "mode": "execute",
                "params": {
                    "title": "Demo Delivery",
                    "context": "Goal: ship the console demo. Risk: visual QA is short.",
                },
                "expected": {
                    "ok": True,
                    "step_count": 1,
                    "tools": ["work_brief_builder"],
                },
            }],
        )
        run = self.manager.evaluate(candidate["id"], suite["id"])
        promotion = self.manager.promote(candidate["id"], actor="tester")
        active = self.registry.execute_skill(
            "delivery_brief",
            {"title": "Demo Delivery", "context": "Goal: ship. Risk: time."},
        )

        self.assertTrue(run["passed"])
        self.assertEqual(promotion["to_version_id"], candidate["id"])
        self.assertTrue(active["ok"])
        self.assertEqual(active["outputs"][0]["tool"], "work_brief_builder")


if __name__ == "__main__":
    unittest.main()
