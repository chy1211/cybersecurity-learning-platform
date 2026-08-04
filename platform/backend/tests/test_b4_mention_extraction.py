from __future__ import annotations

import unittest

from exp_3.b4.mention_extraction import (
    MentionExtractionError,
    build_step1_input,
    parse_mention_payload,
)


QUESTION = {
    "qid": "q1",
    "stem": "下列哪一項可降低 SQL Injection 風險？",
    "options": {
        "A": "輸入驗證",
        "B": "停用 MFA",
        "C": "關閉日誌",
        "D": "增加共用帳號",
    },
    "answer": "A",
}


class MentionExtractionTests(unittest.TestCase):
    def test_step1_input_contains_stem_and_all_options_but_not_answer(self):
        value = build_step1_input(QUESTION)
        self.assertEqual(set(value), {"stem", "options"})
        self.assertEqual(set(value["options"]), {"A", "B", "C", "D"})
        self.assertNotIn("answer", value)

    def test_parses_mentions_with_origin_and_source_span(self):
        raw = {
            "sub_claims": [
                {
                    "subclaim_id": "0",
                    "text": QUESTION["stem"],
                    "mentions": [
                        {
                            "text": "SQL Injection",
                            "origin": "stem",
                            "source_span": "SQL Injection",
                        },
                        {
                            "text": "輸入驗證",
                            "origin": "option_A",
                            "source_span": "輸入驗證",
                        },
                    ],
                }
            ]
        }
        value = parse_mention_payload(raw, QUESTION)
        self.assertEqual(len(value["mentions"]), 2)
        self.assertEqual(value["mentions"][1]["origin"], "option_A")

    def test_rejects_invented_source_span(self):
        raw = {
            "sub_claims": [
                {
                    "text": QUESTION["stem"],
                    "mentions": [
                        {
                            "text": "系統",
                            "origin": "stem",
                            "source_span": "系統",
                        }
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(MentionExtractionError, "not present"):
            parse_mention_payload(raw, QUESTION)

    def test_rejects_legacy_bare_entities_without_provenance(self):
        raw = {"sub_claims": [{"sentence": QUESTION["stem"], "entities": ["MFA"]}]}
        with self.assertRaisesRegex(MentionExtractionError, "mentions array"):
            parse_mention_payload(raw, QUESTION)

    def test_rejects_invalid_origin(self):
        raw = {
            "sub_claims": [
                {
                    "text": QUESTION["stem"],
                    "mentions": [
                        {"text": "MFA", "origin": "option_E", "source_span": "MFA"}
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(MentionExtractionError, "invalid mention origin"):
            parse_mention_payload(raw, QUESTION)


if __name__ == "__main__":
    unittest.main()
