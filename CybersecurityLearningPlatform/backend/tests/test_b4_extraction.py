import unittest

from exp_3.b4.extraction import ExtractionMatrixError, validate_extraction_artifact


class B4ExtractionTests(unittest.TestCase):
    def test_exact_qid_coverage_and_empty_evidence_are_valid(self):
        payload = {
            "q1": {"qid": "q1", "subgraph": {"evidence": []}},
            "q2": {"qid": "q2", "subgraph": {"evidence": [{"head": "a"}]}},
        }
        report = validate_extraction_artifact(payload, qids=["q1", "q2"], model="e4b")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["empty_evidence_questions"], 1)

    def test_missing_and_error_records_fail(self):
        with self.assertRaises(ExtractionMatrixError):
            validate_extraction_artifact(
                {"q1": {"qid": "q1", "error": "timeout", "subgraph": {"evidence": []}}},
                qids=["q1", "q2"],
                model="e4b",
            )


if __name__ == "__main__":
    unittest.main()
