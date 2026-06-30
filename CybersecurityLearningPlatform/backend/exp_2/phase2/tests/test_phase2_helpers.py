import sys
import unittest
from pathlib import Path


PHASE2_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE2_DIR))

from step2_1_leiden import build_size_distribution
from step2_2_ccod import build_ccod_ranking
from step2_4_topo_layer import assign_layers_with_cycle_breaks
from step2_5_topic_label import build_labeling_rows
from step2_6_chapter_dict import parse_source_file, summarize_chapter_counts


class Phase2HelperTests(unittest.TestCase):
    def test_leiden_size_distribution_uses_expected_buckets(self):
        sizes = [1, 2, 3, 9, 10, 49, 50, 99, 100, 101]

        self.assertEqual(
            build_size_distribution(sizes),
            {
                "1-2": 2,
                "3-9": 2,
                "10-49": 2,
                "50-99": 2,
                ">=100": 2,
            },
        )

    def test_ccod_ranking_includes_zero_ccod_communities(self):
        community_sizes = {1: 4, 2: 2, 3: 1}
        cross_edges = [
            {"source_cid": 1, "target_cid": 2, "count": 1},
            {"source_cid": 1, "target_cid": 3, "count": 1},
            {"source_cid": 2, "target_cid": 1, "count": 1},
        ]

        rows = build_ccod_ranking(cross_edges, community_sizes)

        self.assertEqual([row["cid"] for row in rows], [1, 2, 3])
        self.assertEqual([row["ccod"] for row in rows], [2, 1, 0])
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3])
        self.assertEqual([row["community_size"] for row in rows], [4, 2, 1])

    def test_topological_layers_handle_dag(self):
        layers, removed_edges = assign_layers_with_cycle_breaks(
            nodes=["A", "B", "C", "D"],
            edges=[("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )

        self.assertEqual(layers, {"A": 0, "B": 1, "C": 1, "D": 2})
        self.assertEqual(removed_edges, [])

    def test_topological_layers_break_cycles_deterministically(self):
        layers, removed_edges = assign_layers_with_cycle_breaks(
            nodes=["A", "B", "C"],
            edges=[("A", "B"), ("B", "C"), ("C", "B")],
        )

        self.assertEqual(set(layers), {"A", "B", "C"})
        self.assertTrue(all(isinstance(value, int) and value >= 0 for value in layers.values()))
        self.assertEqual(len(removed_edges), 1)

    def test_labeling_export_rows_sort_by_rank_then_name(self):
        records = [
            {"cid": 7, "community_size": 4, "node_name": "zeta", "rank": 2},
            {"cid": 7, "community_size": 4, "node_name": "alpha", "rank": 1},
            {"cid": 7, "community_size": 4, "node_name": "beta", "rank": None},
            {"cid": 8, "community_size": 1, "node_name": "small", "rank": 1},
        ]

        rows = build_labeling_rows(records, min_size=2)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cid"], 7)
        self.assertEqual(rows[0]["top3_nodes"], "alpha, zeta, beta")
        self.assertEqual(rows[0]["assigned_name"], "")

    def test_source_file_parser_handles_chapters_modules_and_unmatched(self):
        self.assertEqual(
            parse_source_file("第06章 系統安全技術與規範_e5.pdf"),
            {"chapter_unit": "06_系統安全技術與規範", "category": "章節"},
        )
        self.assertEqual(
            parse_source_file("教材_第10章_資訊安全管理.pdf"),
            {"chapter_unit": "10_資訊安全管理", "category": "章節"},
        )
        self.assertEqual(
            parse_source_file("iPAS_網路安全簡介_模組4-保護組織.pdf"),
            {"chapter_unit": "M_保護組織", "category": "模組"},
        )
        self.assertEqual(
            parse_source_file("other_type.json"),
            {"chapter_unit": "UNMATCHED", "category": "UNMATCHED"},
        )

    def test_chapter_summary_counts_nodes_and_source_files(self):
        source_to_chapter = {
            "a.pdf": {"chapter_unit": "01_導論", "category": "章節"},
            "b.pdf": {"chapter_unit": "01_導論", "category": "章節"},
            "c.pdf": {"chapter_unit": "UNMATCHED", "category": "UNMATCHED"},
        }
        source_to_node_ids = {
            "a.pdf": {1, 2},
            "b.pdf": {2, 3},
            "c.pdf": {9},
        }

        rows = summarize_chapter_counts(source_to_chapter, source_to_node_ids)

        self.assertEqual(
            rows,
            [
                {"chapter_unit": "01_導論", "node_count": 3, "source_file_count": 2},
                {"chapter_unit": "UNMATCHED", "node_count": 1, "source_file_count": 1},
            ],
        )


if __name__ == "__main__":
    unittest.main()
