import sys
import unittest
from pathlib import Path


PHASE2_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE2_DIR))

from migrate_analysis_properties import (
    APPLY_TOKEN,
    RESTORE_TOKEN,
    ensure_clean_apply_state,
    parse_args,
    require_confirmation,
    validate_post_apply_coverage,
)
from step2_1_leiden import build_size_distribution
from step2_2_ccod import build_ccod_ranking
from step2_4_topo_layer import centrality_layers, dag_layers
from step2_5_topic_label import fetch_community_data
from step2_6_chapter_dict import build_source_mapping, summarize_chapter_counts


class Phase2HelperTests(unittest.TestCase):
    def test_migration_defaults_to_read_only_dry_run(self):
        args = parse_args([])
        self.assertFalse(args.apply)
        self.assertIsNone(args.restore)

    def test_migration_apply_requires_exact_confirmation(self):
        with self.assertRaises(ValueError):
            require_confirmation("apply", "wrong")
        self.assertIsNone(require_confirmation("apply", APPLY_TOKEN))

    def test_migration_restore_requires_exact_confirmation(self):
        with self.assertRaises(ValueError):
            require_confirmation("restore", None)
        self.assertIsNone(require_confirmation("restore", RESTORE_TOKEN))

    def test_migration_refuses_repeated_apply_when_analysis_properties_exist(self):
        with self.assertRaises(RuntimeError):
            ensure_clean_apply_state({
                "out_degree": 10,
                "betweenness": 0,
                "closeness": 0,
                "centrality_layer": 0,
                "dag_layer": 0,
            })
        self.assertIsNone(ensure_clean_apply_state({
            "out_degree": 0,
            "betweenness": 0,
            "closeness": 0,
            "centrality_layer": 0,
            "dag_layer": 0,
        }))

    def test_migration_requires_exact_expected_coverage(self):
        planned = {"all_nodes": 100, "centrality_nodes": 80}
        after = {
            "community_nodes": 100,
            "out_degree": 80,
            "betweenness": 80,
            "closeness": 80,
            "centrality_layer": 100,
            "dag_layer": 100,
        }
        self.assertEqual(after, validate_post_apply_coverage(after, planned))

        broken = dict(after)
        broken["betweenness"] = 79
        with self.assertRaises(RuntimeError):
            validate_post_apply_coverage(broken, planned)

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

    def test_centrality_layers_keep_ties_and_zero_degree_nodes(self):
        layers = centrality_layers(
            [
                {"node_id": 1, "out_deg": 3},
                {"node_id": 2, "out_deg": 3},
                {"node_id": 3, "out_deg": 1},
                {"node_id": 4, "out_deg": 0},
            ]
        )

        self.assertEqual(layers, {1: 0, 2: 0, 3: 1, 4: 2})

    def test_dag_layers_handle_acyclic_graph_and_isolated_node(self):
        layers, removed_edges = dag_layers(
            node_ids=[1, 2, 3, 4, 99],
            edges=[(1, 2), (1, 3), (2, 4), (3, 4)],
        )

        self.assertEqual(layers, {1: 0, 99: 0, 2: 1, 3: 1, 4: 2})
        self.assertEqual(removed_edges, [])

    def test_dag_layers_break_cycles_deterministically(self):
        layers, removed_edges = dag_layers(
            node_ids=[1, 2, 3, 99],
            edges=[(1, 2), (2, 3), (3, 2)],
        )

        self.assertEqual(layers, {1: 0, 3: 0, 99: 0, 2: 1})
        self.assertEqual(removed_edges, [(2, 3)])

    def test_topic_label_rows_sort_by_community_and_out_degree(self):
        records = [
            {
                "cid": 8,
                "sz": 1,
                "node_data": [
                    {
                        "name": "small",
                        "out_deg": 0,
                        "layer": 0,
                        "dag_layer": 0,
                        "ccod_rank": 2,
                        "ccod": 0,
                    }
                ],
            },
            {
                "cid": 7,
                "sz": 3,
                "node_data": [
                    {
                        "name": "zeta",
                        "out_deg": 1,
                        "layer": 1,
                        "dag_layer": 1,
                        "ccod_rank": 1,
                        "ccod": 2,
                    },
                    {
                        "name": "alpha",
                        "out_deg": 2,
                        "layer": 0,
                        "dag_layer": 0,
                        "ccod_rank": 1,
                        "ccod": 2,
                    },
                    {
                        "name": "beta",
                        "out_deg": 1,
                        "layer": 1,
                        "dag_layer": 1,
                        "ccod_rank": 1,
                        "ccod": 2,
                    },
                ],
            },
        ]

        class FakeSession:
            def run(self, _query):
                return records

        rows = fetch_community_data(FakeSession())

        self.assertEqual([row["cid"] for row in rows], [7, 8])
        self.assertEqual(rows[0]["top3_nodes"], "alpha, beta, zeta")
        self.assertEqual(rows[0]["layer_count"], 2)
        self.assertEqual(rows[0]["layer_count_dag"], 2)

    def test_source_file_parser_handles_chapters_modules_and_unmatched(self):
        source_files = [
            "第06章 系統安全技術與規範_e5.pdf",
            "教材_第10章_資訊安全管理.pdf",
            "iPAS_網路安全簡介_模組4-保護組織.pdf",
            "other_type.json",
        ]

        self.assertEqual(
            build_source_mapping(source_files),
            {
                "iPAS_網路安全簡介_模組4-保護組織.pdf": {
                    "chapter_unit": "M_保護組織",
                    "category": "模組",
                },
                "other_type.json": {
                    "chapter_unit": "UNMATCHED",
                    "category": "UNMATCHED",
                },
                "教材_第10章_資訊安全管理.pdf": {
                    "chapter_unit": "10_資訊安全管理",
                    "category": "章節",
                },
                "第06章 系統安全技術與規範_e5.pdf": {
                    "chapter_unit": "06_系統安全技術與規範",
                    "category": "章節",
                },
            },
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
                {
                    "chapter_unit": "01_導論",
                    "category": "章節",
                    "node_count": 3,
                    "source_file_count": 2,
                },
                {
                    "chapter_unit": "UNMATCHED",
                    "category": "UNMATCHED",
                    "node_count": 1,
                    "source_file_count": 1,
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
