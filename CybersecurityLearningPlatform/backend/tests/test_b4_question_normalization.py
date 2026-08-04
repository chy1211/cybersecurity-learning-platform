from __future__ import annotations

import unittest

from exp_3.b4.question_normalization import (
    EXCLUDED_VISUAL_QUESTIONS,
    normalize_question,
    normalize_question_set,
    retrieval_view,
)


def make_record(**overrides):
    record = {
        "id": "IPAS-110-TEC-001",
        "source": "ipas",
        "qtype": "single",
        "stem": "哪一個敘述正確？",
        "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
        "answer": "A",
        "year": 110,
        "split_meta": {"seed": 42},
    }
    record.update(overrides)
    return record


class QuestionNormalizationTests(unittest.TestCase):
    def test_supports_qid_and_is_single_shape(self):
        record = make_record(qid="ISN-107-003", id=None, source="ite", cert_type="ISN")
        normalized = normalize_question(record)
        self.assertEqual(normalized["qid"], "ISN-107-003")
        self.assertEqual(normalized["source"], "ISN")
        self.assertTrue(normalized["is_single"])

    def test_supports_id_and_qtype_shape(self):
        normalized = normalize_question(make_record())
        self.assertEqual(normalized["qid"], "IPAS-110-TEC-001")
        self.assertEqual(normalized["source"], "iPAS")

    def test_options_must_be_exactly_a_to_d(self):
        with self.assertRaisesRegex(ValueError, "exactly A-D"):
            normalize_question(make_record(options={"A": "甲", "B": "乙"}))

    def test_answer_and_single_choice_are_strict(self):
        with self.assertRaisesRegex(ValueError, "answer must match"):
            normalize_question(make_record(answer="AB"))
        with self.assertRaisesRegex(ValueError, "single-choice"):
            normalize_question(make_record(qtype="multiple", is_single=False))

    def test_qids_must_be_unique(self):
        records = [make_record(), make_record()]
        with self.assertRaisesRegex(ValueError, "duplicate qids"):
            normalize_question_set(records)

    def test_retrieval_view_does_not_contain_answer_fields(self):
        normalized = normalize_question(make_record())
        view = retrieval_view(normalized)
        self.assertNotIn("answer", view)
        self.assertNotIn("split_meta", view)
        self.assertEqual(set(view["options"]), {"A", "B", "C", "D"})

    def test_exclusion_manifest_has_exactly_eight_fixed_qids(self):
        self.assertEqual(len(EXCLUDED_VISUAL_QUESTIONS), 8)
        self.assertIn("ISN-107-012", EXCLUDED_VISUAL_QUESTIONS)
        self.assertIn("IPAS-113-MGT-030", EXCLUDED_VISUAL_QUESTIONS)


if __name__ == "__main__":
    unittest.main()
