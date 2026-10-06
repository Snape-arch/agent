"""Verify project provenance and holdout discrimination, not model success."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('project_acceptance',ROOT/'scripts/collaboration_project_acceptance.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)


class ProjectAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def fixture(self):
        project=self.folder/'project';project.mkdir()
        for rel in ('services/__init__.py','services/document_merge.py','services/document_richtext.py','services/response_contract.py'):
            target=project/'clawos'/rel;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/rel).read_bytes())
        for rel in ('clawos/.env','clawos/private.db','tools/weights.gguf','clawos/test_config.json'):
            target=project/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('excluded fixture',encoding='utf-8')
        for cmd in [('init',),('config','core.autocrlf','false'),('add','.'),('-c','user.name=Fixture','-c','user.email=fixture@local','commit','-m','fixture')]:
            harness.Service.git(project,*cmd)
        (project/'clawos/services/document_merge.py').write_text('# unrelated dirty draft',encoding='utf-8')
        out=self.folder/'out';out.mkdir()
        return harness.seed(out,project),out

    def test_snapshot_matches_committed_bytes_excludes_runtime_and_dirty_changes(self):
        repo,out=self.fixture()
        self.assertEqual((repo/harness.PATHS[0]).read_bytes(),(ROOT/'services/document_merge.py').read_bytes())
        for rel in ('clawos/.env','clawos/private.db','tools/weights.gguf','clawos/test_config.json'):
            self.assertFalse((repo/rel).exists())
        self.assertEqual(harness.Service.git(repo,'status','--porcelain').stdout,'')
        self.assertEqual(harness.seed(out),repo)

    def write_correct_targets(self,repo):
        target=repo/harness.PATHS[0];text=target.read_text(encoding='utf-8')
        text=text.replace('def merge_document(base, local, remote):',
            'def merge_document(base, local, remote):\n    for document in (base, local, remote):\n        ids = [block["id"] for block in document["blocks"]]\n        if len(ids) != len(set(ids)):\n            raise MergeConflict("duplicate block IDs")')
        target.write_text(text,encoding='utf-8')
        target=repo/harness.PATHS[1];text=target.read_text(encoding='utf-8')
        text=text.replace('def request_history(messages):','def request_history(messages, *, max_messages=None):')
        text=text.replace('    rows = [dict(',
            '    if max_messages is not None and (type(max_messages) is not int or max_messages <= 0):\n        raise ValueError("invalid history bound")\n    rows = [dict(')
        text=text.replace('    return rows[:last_user] if last_user > 0 else None',
            '    history = rows[:last_user] if last_user > 0 else None\n    return history[-max_messages:] if history is not None and max_messages is not None else history')
        target.write_text(text,encoding='utf-8')

    def check(self,repo,filename):
        return subprocess.run([sys.executable,'-B',filename],cwd=repo,capture_output=True,text=True,timeout=30)

    def test_hidden_tests_fail_original_and_pass_complete_contract(self):
        repo,_=self.fixture()
        original=self.check(repo,'acceptance_holdout.py');self.assertNotEqual(original.returncode,0)
        self.write_correct_targets(repo)
        for script in ('acceptance_public.py','acceptance_holdout.py'):
            result=self.check(repo,script);self.assertEqual(result.returncode,0,result.stderr)

    def test_hidden_rejects_partial_branch_guard_and_bool_bounds(self):
        repo,_=self.fixture();self.write_correct_targets(repo)
        target=repo/harness.PATHS[0]
        target.write_text(target.read_text(encoding='utf-8').replace('for document in (base, local, remote):','for document in (base,):'),encoding='utf-8')
        self.assertNotEqual(self.check(repo,'acceptance_holdout.py').returncode,0)
        self.write_correct_targets(repo)
        target=repo/harness.PATHS[1]
        target.write_text(target.read_text(encoding='utf-8').replace('type(max_messages) is not int','not isinstance(max_messages, int)'),encoding='utf-8')
        self.assertNotEqual(self.check(repo,'acceptance_holdout.py').returncode,0)

    def test_peak_ends_malformed_requests_and_resets_after_crash(self):
        result=dict(nodes=[dict(id='a'),dict(id='b')],events=[
            dict(event='model_started',role='a'),dict(event='model_started',role='b'),
            dict(event='model_receipt',role='a'),dict(event='model_receipt',role='b'),
            dict(event='model_started',role='a_format'),dict(event='coordinator_recovered'),
            dict(event='model_started',role='a'),dict(event='model_receipt',role='a')])
        frozen=copy.deepcopy(result)
        self.assertEqual(harness.peak_workers(result),2);self.assertEqual(result,frozen)


if __name__=='__main__':unittest.main()
