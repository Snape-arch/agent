import unittest
from unittest.mock import patch

from reflection.json_utils import parse_json_value


class ReflectionJsonUtilsTests(unittest.TestCase):
    def test_parses_valid_json_and_preserves_non_json(self):
        self.assertEqual(parse_json_value('{"ok": true}'), {"ok": True})
        self.assertEqual(parse_json_value("not-json"), "not-json")
        marker = {"already": "parsed"}
        self.assertIs(parse_json_value(marker), marker)

    def test_does_not_swallow_interrupts_or_system_exit(self):
        for error in (KeyboardInterrupt(), SystemExit(2)):
            with self.subTest(error=type(error).__name__):
                with patch("reflection.json_utils.json.loads", side_effect=error):
                    with self.assertRaises(type(error)):
                        parse_json_value("{}")


if __name__ == "__main__":
    unittest.main()
