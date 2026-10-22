import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


path = Path(__file__).resolve().parents[1] / 'scripts/windows_health_check.py'
spec = importlib.util.spec_from_file_location('windows_health_check', path)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class LauncherReadinessTests(unittest.TestCase):
    def run_check(self, payload):
        response = MagicMock(status=200)
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(health.sys, 'argv', ['check', '--url', 'http://127.0.0.1:1/health', '--timeout', '1', '--require-ready']), patch.object(health.urllib.request, 'build_opener', return_value=opener), patch.object(health.time, 'monotonic', side_effect=[0, .1, 2]), patch.object(health.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            return health.main()

    def test_ready_current_instance_is_accepted(self):
        self.assertEqual(0, self.run_check({'core_ready': True, 'release': {'restart_required': False}}))

    def test_stale_unready_and_legacy_instances_are_rejected(self):
        for payload in [{'status': 'ok'}, {'core_ready': False, 'release': {'restart_required': False}}, {'core_ready': True, 'release': {'restart_required': True}}, {'core_ready': True, 'release': None}, []]:
            with self.subTest(payload=payload):
                self.assertEqual(1, self.run_check(payload))
