from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "desktop" / "clawos_desktop.py"
SPEC = importlib.util.spec_from_file_location("clawos_desktop", MODULE_PATH)
desktop = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(desktop)


class DesktopPackagingTests(unittest.TestCase):
    def test_smoke_duration_is_bounded_and_optional(self):
        self.assertIsNone(desktop.smoke_duration([]))
        self.assertEqual(desktop.smoke_duration(["--smoke-test"]), 20.0)
        self.assertEqual(desktop.smoke_duration(["--smoke-test=0"]), 1.0)
        self.assertEqual(desktop.smoke_duration(["--smoke-test=500"]), 120.0)

    def test_desktop_environment_separates_mutable_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app_dir = root / "app" / "clawos"
            data_dir = root / "data"
            environment = desktop.desktop_environment(app_dir, data_dir)
            self.assertEqual(environment["CLAWOS_DATA_DIR"], str(data_dir))
            self.assertEqual(environment["CLAWOS_ENV_PATH"], str(data_dir / ".env"))
            self.assertEqual(environment["CLAWOS_MEMORY_DB"], str(data_dir / "memoryos.db"))
            self.assertEqual(environment["CLAWOS_OUTPUT_DIR"], str(data_dir / "output"))
            self.assertEqual(environment["CLAWOS_CONFIG_PATH"], str(app_dir / "config.json"))
            self.assertIn("--disable-gpu", environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"])

    def test_installer_and_acceptance_assets_exist(self):
        for relative in (
            "desktop/ClawOS.iss",
            "desktop/build_desktop.ps1",
            "desktop/clean_machine_acceptance.ps1",
            "desktop/ClawOS-Clean-Machine.wsb",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_build_payload_excludes_private_and_generated_state(self):
        script = (ROOT / "desktop" / "build_desktop.ps1").read_text(encoding="utf-8")
        for marker in ("tmp", "tools", "output", "uploads", "backups", "tests", "docs", "\\.env$", "\\.db$"):
            self.assertIn(marker, script)


if __name__ == "__main__":
    unittest.main()
