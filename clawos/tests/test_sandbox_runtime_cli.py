import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('sandbox_runtime_cli',Path(__file__).resolve().parents[1]/'scripts/sandbox_runtime.py')
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class QuarantineInspection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'CLAWOS_OUTPUT_DIR':self.temp.name})
        self.env.start();self.addCleanup(self.env.stop)
        self.folder=Path(self.temp.name)/'sandbox/commands/owned'
        self.folder.mkdir(parents=True)
        self.request=self.folder/'request.json'
        self.request.write_text(json.dumps(dict(workspace='owned-test-workspace')),encoding='utf-8')

    def test_unbound_success_is_reported_as_quarantined(self):
        (self.folder/'result.json').write_text(json.dumps(dict(cleanup_verified=True,request_digest='wrong')))
        result=cli.inspect_quarantine()
        self.assertEqual(len(result['unresolved']),1)
        self.assertEqual(result['unresolved'][0]['error'],'request digest mismatch')
        self.assertFalse(result['automatic_release'])

    def test_missing_or_invalid_receipts_remain_inspectable(self):
        self.assertEqual(len(cli.inspect_quarantine()['unresolved']),1)
        for value in ('{broken','[]'):
            (self.folder/'result.json').write_text(value)
            self.assertIn('invalid supervisor journal',cli.inspect_quarantine()['unresolved'][0]['error'])
        self.request.write_text('{broken')
        self.assertIsNone(cli.inspect_quarantine()['unresolved'][0]['workspace'])

    def test_bound_clean_receipt_is_not_reported_as_unknown(self):
        digest=hashlib.sha256(self.request.read_bytes()).hexdigest()
        (self.folder/'result.json').write_text(json.dumps(dict(cleanup_verified=True,request_digest=digest)))
        self.assertEqual(cli.inspect_quarantine()['unresolved'],[])

    def test_interrupted_or_malformed_setup_is_reported(self):
        deployment=Path(self.temp.name)/'sandbox/deployment';deployment.mkdir()
        for value in ('{broken','[]',json.dumps(dict(phase='activating',cleanup_verified=False))):
            (deployment/'setup-state.json').write_text(value)
            self.assertTrue(cli.inspect_quarantine()['setup_pending'])

    def test_cli_returns_nonzero_for_unresolved_state_with_json_output(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['sandbox_runtime.py','quarantine']),contextlib.redirect_stdout(output):
            code=cli.main()
        self.assertEqual(code,1)
        self.assertEqual(len(json.loads(output.getvalue())['unresolved']),1)


if __name__=='__main__':unittest.main()
