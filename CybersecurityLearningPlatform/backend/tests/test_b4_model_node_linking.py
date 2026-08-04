from __future__ import annotations

import json
import unittest

from exp_3.b4.model_node_linking import (
    NodeLinkingError,
    build_choice_items,
    build_prompt,
    parse_choices,
)


def make_requests():
    return [
        {
            "qid": "q1",
            "mention": "網站程式碼注入",
            "origin": "stem",
            "candidates": [
                {"element_id": "n1", "name": "SQL Injection", "type": "attack"},
                {"element_id": "n3", "name": "Cross-Site Scripting", "type": "attack"},
            ],
        },
        {
            "qid": "q1",
            "mention": "防火牆",
            "origin": "option_B",
            "candidates": [
                {"element_id": "n5", "name": "防火牆", "type": "control"},
                {"element_id": "n6", "name": "防火牆", "type": "technology"},
            ],
        },
    ]


class BuildTests(unittest.TestCase):
    def test_build_prompt_injects_indexed_mentions(self):
        prompt = build_prompt("<<<<MENTIONS_JSON>>>>", make_requests())
        payload = json.loads(prompt)
        self.assertEqual([m["index"] for m in payload["mentions"]], [0, 1])
        self.assertEqual(payload["mentions"][0]["candidates"][0]["element_id"], "n1")

    def test_empty_candidates_are_rejected(self):
        bad = [{"qid": "q1", "mention": "x", "origin": "stem", "candidates": []}]
        with self.assertRaises(NodeLinkingError):
            build_choice_items(bad)


class ParseTests(unittest.TestCase):
    def test_valid_choices_are_mapped(self):
        requests = make_requests()
        raw = json.dumps(
            {"choices": [{"index": 0, "element_id": "n1"}, {"index": 1, "element_id": "n6"}]}
        )
        self.assertEqual(parse_choices(raw, requests), {0: "n1", 1: "n6"})

    def test_null_pick_is_none(self):
        requests = make_requests()
        raw = {"choices": [{"index": 0, "element_id": None}, {"index": 1, "element_id": "n5"}]}
        self.assertEqual(parse_choices(raw, requests), {0: None, 1: "n5"})

    def test_id_outside_candidate_set_becomes_none(self):
        requests = make_requests()
        # n5 is valid only for index 1; using it for index 0 must fail closed.
        raw = {"choices": [{"index": 0, "element_id": "n5"}, {"index": 1, "element_id": "zzz"}]}
        self.assertEqual(parse_choices(raw, requests), {0: None, 1: None})

    def test_missing_index_defaults_to_none(self):
        requests = make_requests()
        raw = {"choices": [{"index": 0, "element_id": "n1"}]}
        # index 1 was never answered -> None, but still present.
        self.assertEqual(parse_choices(raw, requests), {0: "n1", 1: None})

    def test_extra_and_malformed_entries_are_ignored(self):
        requests = make_requests()
        raw = {
            "choices": [
                {"index": 0, "element_id": "n1"},
                {"index": 9, "element_id": "n1"},  # out of range
                "garbage",
                {"element_id": "n6"},  # no index
            ]
        }
        self.assertEqual(parse_choices(raw, requests), {0: "n1", 1: None})

    def test_fenced_json_is_extracted(self):
        requests = make_requests()
        raw = "```json\n{\"choices\": [{\"index\": 0, \"element_id\": \"n3\"}]}\n```"
        self.assertEqual(parse_choices(raw, requests), {0: "n3", 1: None})

    def test_no_choices_array_raises(self):
        with self.assertRaises(NodeLinkingError):
            parse_choices({"foo": 1}, make_requests())


if __name__ == "__main__":
    unittest.main()
