from __future__ import annotations

import unittest

from exp_3.b4.evidence_ranking import prompt_triples, rank_and_budget_evidence
from exp_3.b4.subgraph import expand_subgraph


EDGES = [
    {"head_id": "n1", "head": "A", "relation": "targets", "tail_id": "n2", "tail": "B"},
    {"head_id": "n2", "head": "B", "relation": "targets", "tail_id": "n3", "tail": "C"},
    {"head_id": "n4", "head": "D", "relation": "mitigates", "tail_id": "n1", "tail": "A"},
]


def fetch_edges(node_ids, relations):
    return [
        edge
        for edge in EDGES
        if edge["relation"] in relations
        and (edge["head_id"] in node_ids or edge["tail_id"] in node_ids)
    ]


class SubgraphAndEvidenceTests(unittest.TestCase):
    def test_two_hop_expands_both_directions_and_keeps_provenance(self):
        result = expand_subgraph(
            [
                {
                    "element_id": "n1",
                    "subclaim_ids": ["0"],
                    "origins": ["stem"],
                    "link_statuses": ["exact"],
                }
            ],
            ["targets", "mitigates"],
            fetch_edges,
            max_hops=2,
            max_triples_per_node=50,
            max_evidence_per_question=100,
        )
        self.assertEqual(
            [(item["head_id"], item["tail_id"]) for item in result["evidence"]],
            [("n1", "n2"), ("n4", "n1"), ("n2", "n3")],
        )
        self.assertTrue(all(item["origins"] == ["stem"] for item in result["evidence"]))

    def test_unselected_relations_are_rejected(self):
        def unfiltered_fetch(node_ids, _relations):
            return [
                edge
                for edge in EDGES
                if edge["head_id"] in node_ids or edge["tail_id"] in node_ids
            ]

        with self.assertRaisesRegex(ValueError, "unselected relation"):
            expand_subgraph(
                [{"element_id": "n1"}],
                ["targets"],
                unfiltered_fetch,
            )

    def test_question_cap_is_recorded(self):
        result = expand_subgraph(
            [{"element_id": "n1"}],
            ["targets", "mitigates"],
            fetch_edges,
            max_evidence_per_question=1,
        )
        self.assertEqual(result["n_after_question_cap"], 1)
        self.assertTrue(result["truncated"])

    def test_ranking_is_deterministic_and_applies_origin_cap(self):
        records = [
            {
                "head_id": "n2", "head": "B", "relation": "targets", "tail_id": "n3", "tail": "C",
                "hop": 2, "origins": ["stem"], "link_statuses": ["exact"], "subclaim_ids": ["0"],
            },
            {
                "head_id": "n1", "head": "A", "relation": "targets", "tail_id": "n2", "tail": "B",
                "hop": 1, "origins": ["option_A"], "link_statuses": ["alias"], "subclaim_ids": ["0"],
            },
            {
                "head_id": "n4", "head": "D", "relation": "mitigates", "tail_id": "n1", "tail": "A",
                "hop": 1, "origins": ["option_A"], "link_statuses": ["exact"], "subclaim_ids": ["1"],
            },
        ]
        result = rank_and_budget_evidence(records, max_per_origin=1, max_total=30)
        self.assertEqual([item["head_id"] for item in result["evidence"]], ["n4", "n2"])
        self.assertEqual(result["origin_counts"]["option_A"], 1)

    def test_prompt_exposes_plain_triples_only(self):
        result = prompt_triples(
            [{"head": "A", "relation": "targets", "tail": "B", "rank": 1}]
        )
        self.assertEqual(result, [["A", "targets", "B"]])


if __name__ == "__main__":
    unittest.main()
