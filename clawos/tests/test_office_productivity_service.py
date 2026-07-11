import tempfile
import unittest
import importlib.util
from email import policy
from email.parser import BytesParser
from pathlib import Path

from services.office_productivity_service import OfficeProductivityService


class OfficeProductivityServiceTests(unittest.TestCase):
    def test_create_and_reopen_professional_formats(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = OfficeProductivityService(allowed_roots=[root])
            sections = [{"heading": "Summary", "paragraphs": ["Delivery is on track."], "table": [["Metric", "Value"], ["Pass rate", "100%"]]}]
            docx = service.create(root / "brief.docx", title="Executive Brief", sections=sections, confirmed=True)
            pdf = service.create(root / "brief.pdf", title="Executive Brief", sections=sections, confirmed=True)
            xlsx = service.create(root / "metrics.xlsx", title="Metrics", data=[{"name": "Metrics", "rows": [["metric", "value"], ["pass", 1]]}], confirmed=True)
            pptx = service.create(root / "deck.pptx", title="Deck", data=[{"title": "Status", "bullets": ["Ready"]}], confirmed=True)
            csv_row = service.create(root / "data.csv", data=[["name", "formula"], ["safe", "=1+1"]], confirmed=True)
            json_row = service.create(root / "data.json", data={"ok": True}, confirmed=True)
            for item in (docx, pdf, xlsx, pptx, csv_row, json_row):
                self.assertTrue(item["valid"], item)
                self.assertEqual(item["quality_gate"], "pass")
                self.assertGreater(item["bytes"], 0)
            self.assertIn("'", (root / "data.csv").read_text(encoding="utf-8-sig"))

    def test_meeting_package_contains_minutes_actions_email_calendar_and_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = OfficeProductivityService(allowed_roots=[root])
            result = service.meeting_package({
                "title": "Product Review",
                "summary": "The team approved the release candidate.",
                "decisions": ["Ship after final QA"],
                "risks": ["Calendar integration credentials pending"],
                "actions": [{"owner": "Alice", "description": "Run QA", "due_date": "2026-07-12", "evidence": "00:03:12"}],
            }, root / "package", recipients=["alice@example.com"], confirmed=True)
            self.assertEqual(result["quality_gate"], "pass")
            formats = {item["format"] for item in result["artifacts"]}
            self.assertTrue({"docx", "pdf", "xlsx", "md", "eml", "ics"} <= formats)
            message = BytesParser(policy=policy.default).parsebytes((root / "package" / "followup.eml").read_bytes())
            self.assertEqual(message["To"], "alice@example.com")
            self.assertTrue(message.is_multipart())
            calendar = (root / "package" / "followup.ics").read_text(encoding="utf-8")
            self.assertIn("BEGIN:VALARM", calendar)
            self.assertIn("DTEND:", calendar)
            self.assertIn("ATTENDEE;RSVP=TRUE:mailto:alice@example.com", calendar)

    def test_email_header_injection_and_unconfirmed_writes_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = OfficeProductivityService(allowed_roots=[root])
            with self.assertRaises(PermissionError):
                service.create(root / "x.docx", title="x")
            with self.assertRaises(ValueError):
                service.create_email_draft(root / "x.eml", subject="Hello\nBcc: stolen@example.com", body="x", to=["a@example.com"], confirmed=True)

    def test_connector_dispatch_requires_confirmation_and_idempotency(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = OfficeProductivityService(
                allowed_roots=[root],
                smtp_sender=lambda data, cfg, key: calls.append(("email", key, len(data))) or {"accepted": 1},
                calendar_sender=lambda data, cfg, key: calls.append(("calendar", key, len(data))) or {"status": 201},
            )
            service.create_email_draft(root / "x.eml", subject="Hello", body="Body", to=["a@example.com"], confirmed=True)
            service.create_calendar_event(root / "x.ics", summary="Review", start="2026-07-12T09:00:00+00:00", attendees=["a@example.com"], confirmed=True)
            with self.assertRaises(PermissionError):
                service.send_email(root / "x.eml", {}, confirmed=True)
            email = service.send_email(root / "x.eml", {}, confirmed=True, idempotency_key="mail-1")
            calendar = service.publish_calendar(root / "x.ics", {}, confirmed=True, idempotency_key="cal-1")
            self.assertTrue(email["sent"])
            self.assertTrue(calendar["published"])
            self.assertEqual([item[0] for item in calls], ["email", "calendar"])

    @unittest.skipUnless(importlib.util.find_spec("openpyxl") and importlib.util.find_spec("docx"), "professional office dependencies unavailable")
    def test_visual_quality_gates_and_advanced_data_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = OfficeProductivityService(allowed_roots=[root])
            sections = [{"heading": "中英文 Mixed-language summary", "paragraphs": ["收入 Revenue 增长稳定。"], "table": [["地区 Region", "收入 Revenue"], ["华东 East", "120"]]}]
            docx = service.create(root / "mixed.docx", title="经营分析 Business Review", sections=sections, confirmed=True)
            docx_quality = service.quality_audit(docx["path"])
            self.assertEqual(docx_quality["quality_gate"], "pass")
            self.assertEqual(docx_quality["visual_status"], "structural_only")
            self.assertIn("rendered_pages", docx_quality["warnings"])

            pdf = service.create(root / "mixed.pdf", title="经营分析 Business Review", sections=sections, confirmed=True)
            pdf_quality = service.quality_audit(pdf["path"], strict_visual=True)
            self.assertEqual(pdf_quality["quality_gate"], "pass", pdf_quality)
            self.assertGreaterEqual(pdf_quality["render"]["pages"], 1)

            rows = [
                {"region": "East", "revenue": 120.0, "cost": 70.0},
                {"region": "East", "revenue": 180.0, "cost": 90.0},
                {"region": "West", "revenue": 100.0, "cost": 65.0},
            ]
            analysis = service.analyze_data(rows, root / "analysis.xlsx", title="Revenue Analysis", group_by="region", metrics=["revenue", "cost"], confirmed=True)
            self.assertEqual(analysis["quality"]["quality_gate"], "pass", analysis)
            self.assertEqual(analysis["grouped"]["East"]["revenue"], 300.0)
            self.assertIn("revenue|cost", analysis["correlations"])
            self.assertTrue((root / "analysis.xlsx").is_file())


if __name__ == "__main__":
    unittest.main()
