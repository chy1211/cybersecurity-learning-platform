from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import export_community_naming_evidence as naming_evidence


class CommunityNamingEvidenceSelectionTests(unittest.TestCase):
    def write_names(self, directory: str) -> Path:
        path = Path(directory) / "community-names.json"
        path.write_text(
            json.dumps(
                {
                    "names": {
                        "1": "Existing reviewed name",
                        "2": "待人工確認（分群 2）",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_all_selection_includes_existing_and_pending_names(self) -> None:
        selector = getattr(naming_evidence, "load_target_ids", None)
        self.assertIsNotNone(selector)
        if selector is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            _, community_ids = selector(self.write_names(temp_dir), "all")

        self.assertEqual([1, 2], community_ids)

    def test_pending_selection_remains_available(self) -> None:
        selector = getattr(naming_evidence, "load_target_ids", None)
        self.assertIsNotNone(selector)
        if selector is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            _, community_ids = selector(self.write_names(temp_dir), "pending")

        self.assertEqual([2], community_ids)

    def test_default_selection_reviews_all_named_communities(self) -> None:
        args = naming_evidence.parse_args([])
        self.assertEqual("all", getattr(args, "selection", None))


if __name__ == "__main__":
    unittest.main()
