import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from office_artifacts import create_docx, create_xlsx
from services.office_editor_service import OfficeEditorService
from services.office_roundtrip_service import OfficeRoundtripService
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary, WindowsFirewallPackageGuard


class AppContainerBoundaryTests(unittest.TestCase):
    def test_mutations_are_confirmation_gated(self):
        boundary = WindowsAppContainerBoundary()
        with self.assertRaises(PermissionError):
            boundary.install()
        with self.assertRaises(PermissionError):
            boundary.uninstall()
        with self.assertRaises(ValueError):
            WindowsAppContainerBoundary("bad profile!")
        guard = WindowsFirewallPackageGuard()
        with self.assertRaises(PermissionError):
            guard.install("S-1-15-2-1")
        with self.assertRaises(PermissionError):
            guard.remove()

    @mock.patch("services.windows_appcontainer_boundary.subprocess.run")
    def test_firewall_rule_is_package_scoped_and_reversible(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="True\n", stderr="")
        guard = WindowsFirewallPackageGuard()
        result = guard.install("S-1-15-2-123", confirmed=True)
        self.assertTrue(result["direct_egress_blocked"])
        command = " ".join(run.call_args_list[0].args[0])
        self.assertIn("-Package", command)
        guard.remove(confirmed=True)
        self.assertTrue(any("Remove-NetFirewallRule" in " ".join(call.args[0]) for call in run.call_args_list))


class OfficeRoundtripTests(unittest.TestCase):
    def test_docx_comments_revisions_and_part_fidelity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "source.docx"; output = root / "output.docx"
            create_docx(source, "Quarterly report", [{"heading": "Summary", "paragraphs": ["Revenue is stable."]}])
            result = OfficeRoundtripService().edit_docx(
                source, output,
                comments=[{"target": "Revenue", "text": "Cite source", "author": "Reviewer"}],
                revisions=[{"old": "stable", "new": "growing", "author": "Editor"}],
            )
            self.assertTrue(result["roundtrip_passed"])
            with zipfile.ZipFile(output) as archive:
                self.assertIn("word/comments.xml", archive.namelist())
                document = archive.read("word/document.xml").decode("utf-8")
                settings = archive.read("word/settings.xml").decode("utf-8")
            self.assertIn("commentRangeStart", document)
            self.assertIn("w:del", document)
            self.assertIn("w:ins", document)
            self.assertIn("trackRevisions", settings)

    def test_xlsx_only_changes_target_sheet_and_preserves_styles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "source.xlsx"; output = root / "output.xlsx"
            create_xlsx(source, [{"name": "Data", "rows": [[1, 2], [3, "=A2+B1"]]}])
            result = OfficeRoundtripService().edit_xlsx(source, output, [{"sheet": "Data", "cell": "A2", "value": 7}])
            self.assertTrue(result["roundtrip_passed"])
            self.assertTrue(result["style_preserved"])
            self.assertEqual(result["unexpected_changed_parts"], [])


class OfficeEditorTests(unittest.TestCase):
    def test_onlyoffice_session_is_signed_and_secrets_are_not_exposed(self):
        env = {
            "ONLYOFFICE_DOCUMENT_SERVER_URL": "https://office.example.test",
            "ONLYOFFICE_JWT_SECRET": "top-secret-value",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            session = OfficeEditorService().create_session(
                "onlyoffice", artifact_id="artifact-1", file_name="report.docx",
                sha256="a" * 64, public_base_url="https://claw.example.test",
            )
            raw = json.dumps(session)
            self.assertEqual(session["mount"]["type"], "onlyoffice-docsapi")
            self.assertIn("token", session["mount"]["config"])
            self.assertNotIn("top-secret-value", raw)
            callback = session["mount"]["config"]["editorConfig"]["callbackUrl"]
            self.assertIn("sig=", callback)

    def test_unconfigured_provider_fails_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                OfficeEditorService().create_session(
                    "onlyoffice", artifact_id="a", file_name="a.docx",
                    sha256="b" * 64, public_base_url="https://example.test",
                )


if __name__ == "__main__":
    unittest.main()
