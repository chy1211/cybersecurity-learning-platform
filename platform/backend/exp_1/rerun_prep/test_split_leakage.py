import unittest

import leakage_check
import split_construction_heldout as split


class SplitConstructionHeldoutTests(unittest.TestCase):
    def test_ipas_null_year_uses_sample_label(self):
        record = {
            "id": "IPAS-NULL-MGT-001",
            "source": "iPAS",
            "subject": "Mgmt",
            "year": None,
            "qtype": "single",
            "stem": "Question?",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "answer": "A",
        }

        self.assertEqual(
            "iPAS|subject=Mgmt|year=SAMPLE",
            split.ipas_strata_key(record, include_qtype=False),
        )

    def test_duplicate_stems_stay_on_same_side_across_strata(self):
        records = [
            split.SplitInput(
                record={"qid": "A-1", "stem": "Duplicate stem.", "options": {}},
                item_id="A-1",
                source="ITE",
                strata_key="s1",
                normalized_stem=split.normalize_stem_for_grouping("Duplicate stem."),
            ),
            split.SplitInput(
                record={"qid": "B-1", "stem": "Duplicate, STEM!", "options": {}},
                item_id="B-1",
                source="ITE",
                strata_key="s2",
                normalized_stem=split.normalize_stem_for_grouping("Duplicate, STEM!"),
            ),
            split.SplitInput(
                record={"qid": "A-2", "stem": "Unique one.", "options": {}},
                item_id="A-2",
                source="ITE",
                strata_key="s1",
                normalized_stem=split.normalize_stem_for_grouping("Unique one."),
            ),
            split.SplitInput(
                record={"qid": "B-2", "stem": "Unique two.", "options": {}},
                item_id="B-2",
                source="ITE",
                strata_key="s2",
                normalized_stem=split.normalize_stem_for_grouping("Unique two."),
            ),
        ]

        result = split.assign_splits(records, ratio=0.5, seed=7)
        side_by_id = {item.item_id: item.side for item in result.items}

        self.assertEqual(side_by_id["A-1"], side_by_id["B-1"])
        self.assertEqual(0, result.duplicate_split_violations)


class LeakageCheckTests(unittest.TestCase):
    def test_detects_stem_leak_after_normalization(self):
        heldout = [
            {
                "qid": "Q-1",
                "stem": "This network security stem leaks.",
                "options": {"A": "short", "B": "Long option that is absent"},
            }
        ]
        corpus = [
            leakage_check.CorpusText(
                path="corpus.txt",
                text="Prefix THIS network-security stem leaks suffix.",
            )
        ]

        result = leakage_check.detect_leaks(heldout, corpus, min_len=10)

        self.assertEqual(1, len(result.leaks))
        self.assertEqual("Q-1", result.leaks[0].question_id)
        self.assertEqual(1, result.skipped_fragments)


if __name__ == "__main__":
    unittest.main()
