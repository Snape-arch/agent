from pathlib import Path
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.config_environment import resolve_environment

class IsolatedServiceImportTests(unittest.TestCase):
    def test_nested_environment_rules(self):
        with patch.dict(os.environ,{'CLAWOS_TEST_VALUE':'configured'},clear=False):
            self.assertEqual(resolve_environment(dict(values=['$'+'{CLAWOS_TEST_VALUE:-fallback}','$'+'{CLAWOS_TEST_ABSENT:-cpu}',3])),dict(values=['configured','cpu',3]))
    def test_recovery_does_not_import_office(self):
        code="import sys;sys.path.insert(0,'clawos');from services import MaintenanceService;assert 'services.office_productivity_service' not in sys.modules;from services.maintenance_service import MaintenanceService as direct;assert direct is MaintenanceService"
        p=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_unknown_export(self):
        import services
        with self.assertRaises(AttributeError):getattr(services,'UnknownService')
if __name__=='__main__':unittest.main()
