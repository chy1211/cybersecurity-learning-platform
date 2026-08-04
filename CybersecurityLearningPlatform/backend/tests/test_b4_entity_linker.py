from __future__ import annotations

import unittest

from exp_3.b4.entity_linker import EntityLinker, LinkerConfig, normalize_name


NODES = [
    {"element_id": "n1", "name": "SQL Injection", "type": "attack"},
    {"element_id": "n2", "name": "Multi-Factor Authentication", "type": "control"},
    {"element_id": "n3", "name": "Cross-Site Scripting", "type": "attack"},
    {"element_id": "n4", "name": "SQL", "type": "technology"},
    # Two nodes with the same normalized name -> exact-collision case.
    {"element_id": "n5", "name": "防火牆", "type": "control"},
    {"element_id": "n6", "name": "防火牆", "type": "technology"},
]


def config():
    return LinkerConfig(
        semantic_top_k=5,
        min_mention_chars=2,
        generic_terms=frozenset({"系統", "資料"}),
    )


def semantic_provider(_mention, _top_k):
    return [
        {"element_id": "n1", "name": "SQL Injection", "score": 0.88},
        {"element_id": "n3", "name": "Cross-Site Scripting", "score": 0.67},
    ]


class NormalizationTests(unittest.TestCase):
    def test_normalization_contract(self):
        self.assertEqual(normalize_name(" SQL  Injection "), "sql injection")
        self.assertEqual(normalize_name("ＭＦＡ"), "mfa")
        self.assertEqual(normalize_name("Cross‑Site–Scripting"), "cross-site-scripting")


class DeterministicLayerTests(unittest.TestCase):
    def test_exact_match_precedes_everything_else(self):
        linker = EntityLinker(NODES, aliases={"SQLi": "SQL Injection"}, config=config())
        result = linker.link(qid="q1", mention="SQL  Injection", origin="stem")
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["matched_node"]["element_id"], "n1")
        self.assertNotIn("needs_choice", result)

    def test_alias_match_requires_approved_mapping(self):
        linker = EntityLinker(NODES, aliases={"SQLi": "SQL Injection"}, config=config())
        result = linker.link(qid="q1", mention="SQLi", origin="option_A")
        self.assertEqual(result["status"], "alias")
        self.assertEqual(result["matched_node"]["name"], "SQL Injection")

    def test_generic_mentions_fail_closed_before_exact(self):
        linker = EntityLinker(NODES, config=config())
        result = linker.link(qid="q1", mention="系統", origin="option_B")
        self.assertEqual(result["status"], "rejected_generic")
        self.assertIsNone(result["matched_node"])

    def test_short_mentions_are_rejected(self):
        linker = EntityLinker(NODES, config=config())
        result = linker.link(qid="q1", mention="s", origin="stem")
        self.assertEqual(result["status"], "rejected_generic")


class NoPickerFailClosedTests(unittest.TestCase):
    def test_non_exact_without_picker_is_unresolved(self):
        linker = EntityLinker(NODES, config=config(), semantic_provider=semantic_provider)
        result = linker.link(qid="q1", mention="網站程式碼注入", origin="stem")
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["candidates"])  # candidates still recorded for audit

    def test_no_candidate_source_is_unresolved(self):
        linker = EntityLinker(NODES, config=config())  # no semantic provider
        result = linker.link(qid="q1", mention="網站程式碼注入", origin="stem")
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["candidates"], [])

    def test_exact_collision_without_picker_is_unresolved(self):
        linker = EntityLinker(NODES, config=config())
        result = linker.link(qid="q1", mention="防火牆", origin="stem")
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(len(result["candidates"]), 2)


class ModelPickTests(unittest.TestCase):
    def test_semantic_candidate_accepted_when_model_picks_valid_id(self):
        linker = EntityLinker(
            NODES,
            config=config(),
            semantic_provider=semantic_provider,
            node_picker=lambda req: "n1",
        )
        result = linker.link(qid="q1", mention="網站程式碼注入", origin="stem")
        self.assertEqual(result["status"], "model_pick")
        self.assertEqual(result["matched_node"]["element_id"], "n1")
        self.assertEqual(len(result["candidates"]), 2)

    def test_model_none_is_unresolved(self):
        linker = EntityLinker(
            NODES,
            config=config(),
            semantic_provider=semantic_provider,
            node_picker=lambda req: None,
        )
        result = linker.link(qid="q1", mention="網站程式碼注入", origin="stem")
        self.assertEqual(result["status"], "unresolved")
        self.assertIn("no candidate", result["decision_reason"])

    def test_model_pick_outside_candidate_set_is_unresolved(self):
        # A hallucinated id that is not among the presented candidates.
        linker = EntityLinker(
            NODES,
            config=config(),
            semantic_provider=semantic_provider,
            node_picker=lambda req: "n999",
        )
        result = linker.link(qid="q1", mention="網站程式碼注入", origin="stem")
        self.assertEqual(result["status"], "unresolved")
        self.assertIn("outside the candidate set", result["decision_reason"])

    def test_exact_collision_resolved_by_model(self):
        picker_calls = []

        def picker(req):
            picker_calls.append(req)
            return "n6"

        linker = EntityLinker(NODES, config=config(), node_picker=picker)
        result = linker.link(qid="q1", mention="防火牆", origin="stem")
        self.assertEqual(result["status"], "model_pick")
        self.assertEqual(result["matched_node"]["element_id"], "n6")
        # The picker saw exactly the two colliding candidates.
        self.assertEqual(picker_calls[0]["choice_kind"], "exact_ambiguous")
        self.assertEqual({c["element_id"] for c in picker_calls[0]["candidates"]}, {"n5", "n6"})


class ProposeFinalizeTests(unittest.TestCase):
    def test_propose_then_finalize_matches_link_and_avoids_re_embedding(self):
        calls = {"n": 0}

        def counting_provider(mention, top_k):
            calls["n"] += 1
            return semantic_provider(mention, top_k)

        linker = EntityLinker(NODES, config=config(), semantic_provider=counting_provider)
        proposed = linker.propose(qid="q1", mention="網站程式碼注入", origin="option_C")
        self.assertTrue(proposed["needs_choice"])
        self.assertEqual(proposed["status"], "pending_choice")
        request = linker.choice_request(proposed)
        self.assertEqual(request["origin"], "option_C")
        final = linker.finalize_choice(proposed, "n1")
        self.assertEqual(final["status"], "model_pick")
        self.assertNotIn("needs_choice", final)
        # propose did exactly one embedding call; finalize did none.
        self.assertEqual(calls["n"], 1)

    def test_every_result_keeps_source_and_candidates(self):
        linker = EntityLinker(NODES, aliases={"SQLi": "SQL Injection"}, config=config())
        result = linker.link(
            qid="q1", mention="SQLi", origin="option_C", source_span="SQLi"
        )
        self.assertEqual(result["qid"], "q1")
        self.assertEqual(result["origin"], "option_C")
        self.assertEqual(result["source_span"], "SQLi")
        self.assertIn("candidates", result)
        self.assertIn("decision_reason", result)


if __name__ == "__main__":
    unittest.main()
