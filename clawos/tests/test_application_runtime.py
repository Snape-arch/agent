import contextlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/application_runtime.py'
SPEC = importlib.util.spec_from_file_location('application_runtime', SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class ApplicationRuntimeTests(unittest.TestCase):
    def test_locked_dependency_inventory_rejects_system_leaks_and_version_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [dict(name='one_package', version='1.0', location=str(root / 'Lib/site-packages'))]
            expected = {'one-package': '1.0'}
            def check(actual=rows, system=False):
                return runtime.validate_inventory(expected, actual, root, system, [3, 12, 14], 'AMD64')
            self.assertEqual(expected, check())
            for actual, system in [([], False), (rows * 2, False), (rows, True),
                    ([dict(rows[0], version='2.0')], False),
                    ([dict(rows[0], location=str(root.parent / 'global/site-packages'))], False),
                    (rows + [dict(rows[0], name='unexpected')], False)]:
                with self.subTest(actual=actual, system=system), self.assertRaises(ValueError):
                    check(actual, system)

    def test_wrong_python_or_architecture_is_rejected(self):
        for version, arch in [([3, 14, 2], 'AMD64'), ([3, 12, 14], 'ARM64')]:
            with self.subTest(version=version, arch=arch), self.assertRaises(ValueError):
                runtime.validate_inventory({}, [], Path.cwd(), False, version, arch)

    def test_selected_pointer_cannot_escape_or_follow_directory_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ['../outside', 'C:/outside', '', 'windows-py312-aaaaaaaaaaaa-bbbbbbbb/../other']:
                (root / 'current.json').write_text(json.dumps(dict(directory=name)))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    runtime.selected_runtime(root)

    def test_changed_interpreter_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Scripts').mkdir()
            exe = root / 'Scripts/python.exe'
            exe.write_bytes(b'fixture')
            saved = {'schema': 'fixture', 'profile': 'fixture', 'executable': str(exe),
                     'prefix': str(root), 'executable_sha256': 'old'}
            (root / runtime.MARKER).write_text(json.dumps(saved))
            with patch.object(runtime, 'child_probe', return_value=dict(saved, executable_sha256='changed')):
                with self.assertRaisesRegex(ValueError, 'executable_sha256'):
                    runtime.verify(exe)

    def test_failed_install_preserves_active_runtime_and_failed_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root / 'requirements.txt'
            lock.write_text('fixture')
            original = b'{"directory":"previous"}'
            (root / 'current.json').write_bytes(original)
            with patch.object(runtime, 'RUNTIMES', root), \
                 patch.object(runtime, 'load_lock', return_value=(lock, {})), \
                 patch.object(runtime, 'prepare_lock', return_value=contextlib.nullcontext()), \
                 patch.object(runtime.subprocess, 'check_output', return_value='["win32",[3,12],"AMD64"]'), \
                 patch.object(runtime.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'venv')):
                with self.assertRaises(subprocess.CalledProcessError):
                    runtime.prepare(sys.executable)
            self.assertEqual(original, (root / 'current.json').read_bytes())
            failures = list(root.glob('windows-py312-*/state.json'))
            self.assertEqual(1, len(failures))
            self.assertEqual('failed', json.loads(failures[0].read_text())['status'])

    def test_child_environment_does_not_forward_credentials_or_package_overrides(self):
        with patch.dict(runtime.os.environ, {'MODEL_API_KEY': 'fixture-private',
                'PIP_EXTRA_INDEX_URL': 'https://private.invalid', 'PYTHONPATH': '/outside'}, clear=True):
            env = runtime.clean_environment()
        self.assertNotIn('MODEL_API_KEY', env)
        self.assertNotIn('PIP_EXTRA_INDEX_URL', env)
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual('1', env['CLAWOS_SKIP_LOCAL_ENV'])

    def test_committed_lock_matches_inputs_and_has_only_pinned_hashes(self):
        lock, rows = runtime.load_lock()
        self.assertGreater(len(rows), 25)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'deployment'
            root.mkdir()
            for path in runtime.DEPLOYMENT.glob('windows-py312.*'):
                (root / path.name).write_bytes(path.read_bytes())
            (root.parent / 'requirements-test.txt').write_bytes((runtime.PROJECT / 'requirements-test.txt').read_bytes())
            path = root / lock.name
            # The same checkout with CRLF remains the same dependency contract.
            for item in [path,root/'windows-py312.in',root.parent/'requirements-test.txt']:
                item.write_bytes(item.read_text().replace('\n','\r\n').encode('utf-8'))
            self.assertEqual(rows,runtime.load_lock(root)[1])
            path.write_text(path.read_text() + 'extra==1.0 --hash=sha256:' + 'a' * 64 + '\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                runtime.load_lock(root)


if __name__ == '__main__':
    unittest.main()
