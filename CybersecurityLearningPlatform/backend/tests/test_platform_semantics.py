from __future__ import annotations

import unittest
from unittest.mock import patch
import json
import os
import tempfile

import app as platform_app
import persistence_service
from neo4j_service import Neo4jService


class _Result:
    def __init__(self, records=None, single=None):
        self._records = list(records or [])
        self._single = single

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._single


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        normalized = " ".join(query.split())
        if "target.communityId AS community" in normalized:
            return _Result(single={"name": params["name"], "community": 1})
        if "analysis_node_count" in normalized and "n.communityId = $community" in normalized:
            return _Result(single={"community_node_count": 5, "analysis_node_count": 0})
        if "analysis_node_count" in normalized:
            return _Result(single={"community_node_count": 2554, "analysis_node_count": 0})
        if "MATCH (s)-[r]->(t)" in normalized:
            return _Result(records=[])
        if "n.name IN $names" in normalized:
            return _Result(
                records=[
                    {
                        "name": params["names"][0],
                        "community": 1,
                        "layer": None,
                        "outDegree": None,
                    }
                ]
            )
        raise AssertionError(f"Unexpected query: {normalized}")


class _Driver:
    def session(self):
        return _Session()


class _PartialSession:
    def __init__(self, empty_items=False):
        self.empty_items = empty_items

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        normalized = " ".join(query.split())
        if "target.communityId AS community" in normalized:
            community = 2 if params["name"] == "unanalyzed" else 1
            return _Result(single={"name": params["name"], "community": community})
        if "analysis_node_count" in normalized and "n.communityId = $community" in normalized:
            if params["community"] == 1:
                return _Result(single={"community_node_count": 2, "analysis_node_count": 2})
            return _Result(single={"community_node_count": 2, "analysis_node_count": 0})
        if "analysis_node_count" in normalized:
            return _Result(single={"community_node_count": 4, "analysis_node_count": 2})
        if "RETURN community, collect" in normalized:
            return _Result(records=[{"community": 1, "nodes": [{"name": "A", "outDegree": 2, "layer": 0}]}])
        if "n.communityId = $community" in normalized and "RETURN n.name AS name" in normalized:
            if self.empty_items:
                return _Result(records=[])
            return _Result(records=[
                {"name": "A", "community": 1, "layer": 0, "outDegree": 2},
                {"name": "B", "community": 1, "layer": 1, "outDegree": 0},
            ])
        raise AssertionError(f"Unexpected partial query: {normalized}")


class _PartialDriver:
    def __init__(self, empty_items=False):
        self.empty_items = empty_items

    def session(self):
        return _PartialSession(self.empty_items)


class PlatformSemanticContractTests(unittest.TestCase):
    def setUp(self):
        platform_app.app.config.update(TESTING=True)
        platform_app._rate_hits.clear()
        self.client = platform_app.app.test_client()

    def test_removed_placeholder_routes_are_not_exposed(self):
        for method, path in (
            ("get", "/api/skill-tree"),
            ("get", "/api/placement-test"),
            ("post", "/api/placement-test/submit"),
            ("post", "/api/node/complete"),
        ):
            response = getattr(self.client, method)(path, json={})
            self.assertEqual(404, response.status_code, path)

    def test_legacy_skill_tree_schema_has_been_removed(self):
        self.assertFalse(hasattr(Neo4jService, "get_skill_tree_data"))

    def test_plan_reports_analysis_unavailable_instead_of_target_only_success(self):
        service = Neo4jService.__new__(Neo4jService)
        service.driver = _Driver()

        result = service.plan_learning_path("target", [], "community")

        self.assertEqual("analysis_unavailable", result["status"])
        self.assertEqual([], result["path"])
        self.assertEqual(0, result["analysis_node_count"])
        self.assertEqual(5, result["community_node_count"])
        self.assertEqual("community", result["target_scope"]["mode"])
        self.assertEqual(1, result["target_scope"]["community"])
        self.assertEqual("unavailable", result["target_scope"]["analysis_state"])
        self.assertEqual(0, result["target_scope"]["analysis_node_count"])
        self.assertEqual(5, result["target_scope"]["community_node_count"])

    def test_learning_path_route_preserves_analysis_unavailable_status(self):
        unavailable = {
            "status": "analysis_unavailable",
            "message": "analysis missing",
            "path": [],
        }
        with patch.object(platform_app.db_service, "plan_learning_path", return_value=unavailable):
            response = self.client.post(
                "/api/learning-paths/plan",
                json={"target_node": "target", "learned_nodes": [], "mode": "community"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("analysis_unavailable", response.get_json()["status"])

    def test_group_endpoints_do_not_return_all_null_analysis_as_success(self):
        service = Neo4jService.__new__(Neo4jService)
        service.driver = _Driver()

        communities = service.get_community_learning_paths()
        chapters = service.get_chapter_learning_paths()

        self.assertEqual("analysis_unavailable", communities["status"])
        self.assertEqual("analysis_unavailable", chapters["status"])
        self.assertEqual([], communities["path"])
        self.assertEqual([], chapters["path"])

    def test_group_endpoint_reports_partial_coverage_explicitly(self):
        service = Neo4jService.__new__(Neo4jService)
        service.driver = _PartialDriver()

        result = service.get_community_learning_paths()

        self.assertEqual("partial", result["status"])
        self.assertEqual("partial", result["analysis_state"])
        self.assertEqual(2, result["analysis_node_count"])
        self.assertEqual(4, result["community_node_count"])
        self.assertEqual(1, len(result["groups"]))

    def test_plan_uses_target_community_coverage_not_global_coverage(self):
        service = Neo4jService.__new__(Neo4jService)
        service.driver = _PartialDriver()

        analyzed = service.plan_learning_path("analyzed", [], "community")
        unanalyzed = service.plan_learning_path("unanalyzed", [], "community")

        self.assertEqual("ok", analyzed["status"])
        self.assertEqual(2, len(analyzed["items"]))
        self.assertEqual("community", analyzed["target_scope"]["mode"])
        self.assertEqual(1, analyzed["target_scope"]["community"])
        self.assertEqual("complete", analyzed["target_scope"]["analysis_state"])
        self.assertEqual(2, analyzed["target_scope"]["analysis_node_count"])
        self.assertEqual(2, analyzed["target_scope"]["community_node_count"])
        self.assertEqual("analysis_unavailable", unanalyzed["status"])
        self.assertEqual([], unanalyzed["items"])
        self.assertEqual("community", unanalyzed["target_scope"]["mode"])
        self.assertEqual(2, unanalyzed["target_scope"]["community"])
        self.assertEqual("unavailable", unanalyzed["target_scope"]["analysis_state"])
        self.assertEqual(0, unanalyzed["target_scope"]["analysis_node_count"])
        self.assertEqual(2, unanalyzed["target_scope"]["community_node_count"])

    def test_plan_never_returns_ok_with_empty_items(self):
        service = Neo4jService.__new__(Neo4jService)
        service.driver = _PartialDriver(empty_items=True)

        result = service.plan_learning_path("analyzed", [], "community")

        self.assertEqual("analysis_unavailable", result["status"])
        self.assertEqual([], result["items"])
        self.assertIn("不一致", result["message"])

    def test_ready_health_fails_closed_when_neo4j_is_unavailable(self):
        with patch.object(platform_app.db_service, "check_readiness", return_value=(False, "database_unavailable")):
            response = self.client.get("/api/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual("not_ready", response.get_json()["status"])

    def test_internal_exception_is_not_returned_to_client(self):
        with patch.object(
            platform_app.db_service,
            "get_overview_stats",
            side_effect=RuntimeError("SENTINEL_PRIVATE_DETAIL"),
        ):
            response = self.client.get("/api/overview-stats")

        body = response.get_json()
        self.assertEqual(500, response.status_code)
        self.assertEqual("internal_service_error", body["error"])
        self.assertIn("request_id", body)
        self.assertNotIn("SENTINEL_PRIVATE_DETAIL", response.get_data(as_text=True))

    def test_chat_returns_ranked_context_evidence(self):
        graph_context = {
            "seeds": [
                {"name": "SQL Injection", "type": "technique", "score": 100, "match_type": "exact"}
            ],
            "nodes": [
                {"name": "SQL Injection", "type": "technique", "is_seed": True},
                {"name": "database", "type": "system", "is_seed": False},
            ],
            "edges": [
                {
                    "source": "SQL Injection",
                    "relation": "can_exploit",
                    "relation_label": "can_exploit",
                    "target": "database",
                    "source_files": ["CH01"],
                    "links_two_seeds": False,
                }
            ],
            "stats": {
                "seed_count": 1,
                "node_count": 2,
                "edge_count": 1,
                "total_edges_found": 1,
                "truncated": False,
            },
            "retrieval": {"mode": "multi_seed_one_hop", "max_seeds": 3, "max_edges": 60},
        }
        with patch.object(
            platform_app.db_service, "get_graph_rag_subgraph", return_value=graph_context
        ), patch.object(platform_app.llm_service, "generate_answer_with_context", return_value="answer"):
            response = self.client.post("/api/chat", json={"message": "SQL Injection"})

        body = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("multi_seed_one_hop", body["retrieval_mode"])
        self.assertEqual("SQL Injection", body["context_entity"])
        # evidence 必須逐條對應送進模型的邊，畫面顯示的依據才等於模型看到的內容
        self.assertEqual(1, len(body["evidence"]))
        self.assertEqual("can_exploit", body["evidence"][0]["relationship"])
        self.assertEqual(1, len(body["graph_context"]["edges"]))

    def test_cors_does_not_allow_unconfigured_origin(self):
        response = self.client.get("/api/health/live", headers={"Origin": "https://attacker.example"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_chat_rate_limit_returns_429(self):
        with patch.object(platform_app.Config, "RATE_LIMIT_REQUESTS", 1), patch.object(
            platform_app.db_service, "get_graph_rag_subgraph", return_value=None
        ):
            first = self.client.post("/api/chat", json={"message": "first"})
            second = self.client.post("/api/chat", json={"message": "second"})
        self.assertEqual(200, first.status_code)
        self.assertEqual(429, second.status_code)

    def test_persistence_failure_does_not_return_false_success(self):
        with patch.object(platform_app.persistence_service, "load_progress", return_value=[]), patch.object(
            platform_app.persistence_service, "save_progress", return_value=False
        ):
            response = self.client.post("/api/user-progress/toggle", json={"node_id": "n1"})
        self.assertEqual(500, response.status_code)
        self.assertEqual("internal_service_error", response.get_json()["error"])


class PersistenceContractTests(unittest.TestCase):
    def test_atomic_replace_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "progress.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(["original"], handle)
            with patch.object(persistence_service, "DATA_FILE", path), patch(
                "persistence_service.os.replace", side_effect=OSError("replace failed")
            ):
                saved = persistence_service.save_progress(["new"])
            with open(path, "r", encoding="utf-8") as handle:
                persisted = json.load(handle)
        self.assertFalse(saved)
        self.assertEqual(["original"], persisted)


class _SearchSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, parameters=None, **params):
        self.query = query
        self.params = params
        return _Result(records=[{"name": "common criteria", "score": 100, "match_type": "exact"}])


class SearchEntityContractTests(unittest.TestCase):
    def test_search_parameter_does_not_collide_with_driver_query_argument(self):
        session = _SearchSession()
        service = Neo4jService.__new__(Neo4jService)
        service.driver = type("Driver", (), {"session": lambda self: session})()

        result = service.search_entities("common criteria")

        self.assertEqual("common criteria", result[0]["name"])
        self.assertIn("$search_query", session.query)
        self.assertEqual("common criteria", session.params["search_query"])


class _RawSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        normalized = " ".join(query.split())
        if "count(n) AS total_nodes" in normalized:
            return _Result(single={"total_nodes": 3})
        if "count(r) AS total_edges" in normalized:
            return _Result(single={"total_edges": 2})
        if "elementId(n) AS id" in normalized and "MATCH (n)-[r]->(m)" not in normalized:
            return _Result(
                records=[
                    {"id": "n1", "label": "A", "type": "concept"},
                    {"id": "n2", "label": "B", "type": "concept"},
                    {"id": "n3", "label": "isolated", "type": "concept"},
                ]
            )
        if "MATCH (n)-[r]->(m)" in normalized:
            return _Result(
                records=[
                    {"source": "n1", "relationship": "related_to", "target": "n2"},
                    {"source": "n2", "relationship": "uses", "target": "n1"},
                ][: params["limit"]]
            )
        raise AssertionError(f"Unexpected raw graph query: {normalized}")


class RawGraphContractTests(unittest.TestCase):
    def test_raw_graph_includes_isolated_nodes_and_explicit_counts(self):
        service = Neo4jService.__new__(Neo4jService)
        service.driver = type("Driver", (), {"session": lambda self: _RawSession()})()

        result = service.get_raw_knowledge_graph(limit=1)

        self.assertEqual(3, result["total_nodes"])
        self.assertEqual(2, result["total_edges"])
        self.assertEqual(3, result["returned_nodes"])
        self.assertEqual(1, result["returned_edges"])
        self.assertTrue(result["truncated"])
        self.assertIn("isolated", {node["label"] for node in result["nodes"]})


if __name__ == "__main__":
    unittest.main()
