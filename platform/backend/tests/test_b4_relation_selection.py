from __future__ import annotations

import unittest

from exp_3.b4.relation_selection import RelationSelectionError, parse_relation_selection


class RelationSelectionTests(unittest.TestCase):
    CANDIDATES = ["mitigates", "targets", "related_to"]

    def test_accepts_only_a_candidate_subset(self):
        result = parse_relation_selection(
            {"selected_relations": ["targets"], "decision_reason": "directly relevant"},
            self.CANDIDATES,
        )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_relations"], ["targets"])

    def test_empty_selection_is_valid(self):
        result = parse_relation_selection(
            {"selected_relations": [], "decision_reason": "no relevant relation"},
            self.CANDIDATES,
        )
        self.assertEqual(result["status"], "empty")

    def test_unknown_relation_is_error_not_fallback(self):
        with self.assertRaisesRegex(RelationSelectionError, "non-candidates"):
            parse_relation_selection(
                {"selected_relations": ["invented_relation"]}, self.CANDIDATES
            )

    def test_invalid_json_is_error_not_fallback(self):
        with self.assertRaisesRegex(RelationSelectionError, "does not contain JSON"):
            parse_relation_selection("not-json", self.CANDIDATES)

    def test_duplicate_and_over_limit_are_errors(self):
        with self.assertRaisesRegex(RelationSelectionError, "duplicates"):
            parse_relation_selection(
                {"selected_relations": ["targets", "targets"]}, self.CANDIDATES
            )
        with self.assertRaisesRegex(RelationSelectionError, "exceeds"):
            parse_relation_selection(
                {"selected_relations": list(self.CANDIDATES)},
                self.CANDIDATES,
                max_relations=2,
            )


if __name__ == "__main__":
    unittest.main()
