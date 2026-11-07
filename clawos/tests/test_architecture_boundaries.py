"""Keep domain dependencies and the consolidated maintenance budgets enforceable."""
import tempfile
import unittest
from pathlib import Path
import shutil

from scripts.architecture_check import APP, DIRECTORY_BUDGETS, FILE_BUDGETS, inspect_architecture


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_current_maintained_boundaries_pass(self):
        report = inspect_architecture()
        self.assertTrue(report['passed'], report['errors'])

    def test_reverse_dependency_and_frontend_cycle_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in FILE_BUDGETS:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(APP / name, target)
            for name in DIRECTORY_BUDGETS:
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / 'api/regression.py').write_text('import clawos_server\n')
            (root / 'static/assets/console/regression.js').write_text("import { refresh } from './shell.js';\n")
            report = inspect_architecture(root)
            self.assertFalse(report['passed'])
            self.assertTrue(any('composition root' in error for error in report['errors']))
            self.assertTrue(any('feature' in error for error in report['errors']))
