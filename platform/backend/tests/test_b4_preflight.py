from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from exp_3.b4.preflight import (
    PreflightError,
    build_freeze_manifest,
    expected_result_keys,
    validate_result_matrix,
    verify_freeze_manifest,
)


class PreflightTests(unittest.TestCase):
    def test_expected_matrix_has_model_qid_condition_product(self):
        keys = expected_result_keys(["q1", "q2"], ["e4b", "gptoss"])
        self.assertEqual(len(keys), 8)
        self.assertIn(("e4b", "q1", "base"), keys)

    def test_complete_matrix_passes(self):
        results = {
            "e4b": {
                "q1": {
                    "base": {"answer_norm": "A"},
                    "rag": {"answer_norm": "B"},
                }
            }
        }
        report = validate_result_matrix(results, qids=["q1"], models=["e4b"])
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["expected_records"], 2)

    def test_missing_arm_and_error_are_hard_failures(self):
        results = {"e4b": {"q1": {"base": {"answer_norm": "A"}}}}
        with self.assertRaisesRegex(PreflightError, "missing condition"):
            validate_result_matrix(results, qids=["q1"], models=["e4b"])
        results["e4b"]["q1"]["rag"] = {"answer_norm": "A", "_api_error": "timeout"}
        with self.assertRaisesRegex(PreflightError, "_api_error"):
            validate_result_matrix(results, qids=["q1"], models=["e4b"])

    def test_freeze_manifest_hashes_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"version":"v1"}\n', encoding="utf-8")
            manifest = build_freeze_manifest([path], metadata={"threshold": 0.8})
            self.assertEqual(manifest["status"], "FROZEN")
            self.assertEqual(len(manifest["files"]), 1)
            self.assertEqual(len(manifest["manifest_sha256"]), 64)

    def test_freeze_manifest_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"version":"v1"}\n', encoding="utf-8")
            manifest = build_freeze_manifest([path], metadata={"threshold": 0.8})
            manifest_path = Path(temp) / "freeze.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(verify_freeze_manifest(manifest_path)["status"], "FROZEN")
            path.write_text('{"version":"v2"}\n', encoding="utf-8")
            with self.assertRaises(PreflightError):
                verify_freeze_manifest(manifest_path)


if __name__ == "__main__":
    unittest.main()
