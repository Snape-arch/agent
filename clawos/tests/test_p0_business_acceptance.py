import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/p0_business_acceptance.py'
SPEC=importlib.util.spec_from_file_location('p0_business_acceptance',SCRIPT)
acceptance=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class BusinessAcceptanceTests(unittest.TestCase):
    def test_real_model_opt_in_rejects_remote_credentials_and_non_api_urls(self):
        for value in ('https://127.0.0.1:8000/v1','http://example.com/v1',
                      'http://localhost:8000/v1','http://user:secret@127.0.0.1/v1',
                      'http://@127.0.0.1/v1','http://127.0.0.1/v1?key=value',
                      'http://127.0.0.1/v1#secret','http://127.0.0.1/v2',
                      'http://127.0.0.1:70000/v1'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                acceptance.local_model_endpoint(value)
        self.assertEqual('http://127.0.0.1:18943/v1',acceptance.local_model_endpoint('http://127.0.0.1:18943/v1'))
        self.assertEqual('http://[::1]:18943/v1',acceptance.local_model_endpoint('http://[::1]:18943/v1'))

    def test_failed_model_preflight_preserves_receipt_and_never_launches_app(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            argv=[str(SCRIPT),'--python',sys.executable,'--embedding-model',td,
                  '--local-model-url','http://127.0.0.1:18943/v1']
            with patch.object(acceptance,'PROJECT',root),patch.object(acceptance,'verify',return_value={}),\
                 patch.object(sys,'argv',argv),patch('httpx.Client.get',side_effect=httpx.ConnectError('private transport detail')),\
                 patch.object(acceptance.subprocess,'Popen') as launch,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(1,acceptance.main())
            launch.assert_not_called()
            reports=list((root/'output/p0-business').glob('*/report.json'))
            self.assertEqual(1,len(reports))
            result=json.loads(reports[0].read_text())
            self.assertFalse(result['passed'])
            self.assertEqual('model_preflight',result['stage'])
            self.assertEqual('ConnectError',result['error'])
            self.assertEqual(0,result['model_generation_calls'])
            self.assertNotIn('private transport detail',reports[0].read_text())


if __name__=='__main__':unittest.main()
