"""Check the actual tool entry honors isolated QA output/DB paths."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import scripts.scenario_tools as scenario


class EntryTests(unittest.TestCase):
    def check_entry(self, reliable):
        captured={}
        class Service:
            def __init__(self,*args,**kwargs):captured.update(kwargs)
            async def run(self,*args,**kwargs):
                captured["run"]=kwargs
                return {"status":"fixture"}
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,CLAWOS_OUTPUT_DIR=folder,CLAWOS_MEMORY_DB=str(Path(folder)/"isolated.db")),\
                 patch("providers.create_model_provider",return_value=object()),\
                 patch("memoryos.memory_store.MemoryStore",return_value=object()),\
                 patch("services.reliable_collaboration.ReliableCollaborationService",Service),\
                 patch("services.autonomous_subagent_service.AutonomousSubagentService",Service):
                body=dict(objective="fixture",roles=[],confirmed=True)
                if reliable:body.update(team_profile="reliable_coding",repo_path=folder,allowed_paths=["a.py"],test_commands=[["python","check.py"]])
                result=scenario.autonomous_subagents(body)
                self.assertEqual(result["status"],"fixture")
                self.assertEqual(captured["root" if reliable else "checkpoint_root"],
                                 Path(folder)/("collaboration-runs" if reliable else "subagents"))
                if reliable:
                    self.assertTrue(captured["run"]["confirmed"])
                    self.assertEqual(captured["run"]["allowed_paths"],["a.py"])

    def test_reliable_tool_routes_to_isolated_root(self):self.check_entry(True)
    def test_legacy_tool_uses_the_same_output_override(self):self.check_entry(False)


if __name__=="__main__":unittest.main()
