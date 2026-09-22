import unittest

from services.ocr_candidate_selector import OCRCandidateSelector


class OCRCandidateSelectorTests(unittest.TestCase):
    def select(self, original, candidates, context=""):
        return OCRCandidateSelector.select(
            original, candidates, context_text=context, original_confidence=.7,
        )

    def test_bounded_percentage_and_unit_consensus_correct_generic_ocr_errors(self):
        percentage = self.select(
            "准确率提升至959%+",
            [{"text": "准确率提升至95%+", "view": "v1", "confidence": .8}],
        )
        self.assertTrue(percentage["auto_applied"])
        self.assertEqual(percentage["selected_text"], "准确率提升至95%+")

        unit = self.select(
            "已知任务<1秒，比官方快7信",
            [
                {"text": "已知任务<1秒，比官方快7倍", "view": "v1", "confidence": .8},
                {"text": "已知任务<1秒，比官方快7倍", "view": "v2", "confidence": .8},
            ],
        )
        self.assertTrue(unit["auto_applied"])
        self.assertIn("7倍", unit["selected_text"])

    def test_same_shape_acronym_and_three_view_identifier_consensus(self):
        acronym = self.select(
            "Al 永远停留在初始水平",
            [{"text": "AI 永远停留在初始水平", "view": "v1", "confidence": .8}],
        )
        self.assertEqual(acronym["selected_text"], "AI 永远停留在初始水平")

        consensus = self.select(
            "ClawoOs能力",
            [{"text": "ClawOs能力", "view": f"v{i}", "confidence": .8} for i in range(3)],
        )
        self.assertTrue(consensus["auto_applied"])
        self.assertEqual(consensus["selected_text"], "ClawOs能力")

    def test_two_view_local_phrase_can_fix_more_than_the_numeric_suffix(self):
        result = self.select(
            "己知任务<1秒，比MTClaw官方快7信",
            [
                {"text": "已知任务<1秒，比MTClaw官方快7倍", "view": "v1", "confidence": .8},
                {"text": "已知任务<1秒，比MTClaw官方快7倍", "view": "v2", "confidence": .8},
            ],
            context="已知任务应当复用文档中的术语。",
        )
        self.assertTrue(result["auto_applied"])
        self.assertEqual(result["selected_text"], "已知任务<1秒，比MTClaw官方快7倍")

    def test_unrelated_candidate_and_single_weak_view_stay_for_human_review(self):
        unrelated = self.select(
            "用户偏好无法保存",
            [{"text": "完全不同的内容", "view": "v1", "confidence": .99}],
        )
        self.assertFalse(unrelated["auto_applied"])
        self.assertEqual(unrelated["selected_text"], "用户偏好无法保存")

        weak = self.select(
            "ClawoOs能力",
            [{"text": "ClawOs能力", "view": "v1", "confidence": .8}],
        )
        self.assertFalse(weak["auto_applied"])


if __name__ == "__main__":
    unittest.main()
