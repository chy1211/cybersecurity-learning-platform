from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.smoke_test_platform import (
    Endpoint,
    HttpResult,
    build_endpoints,
    run_smoke,
)


def clean_payloads() -> dict[tuple[str, str], tuple[int, object]]:
    unavailable = {
        "status": "analysis_unavailable",
        "analysis_node_count": 0,
        "groups": [],
    }
    return {
        ("GET", "/api/health/live"): (200, {"status": "live"}),
        ("GET", "/api/health/ready"): (
            200,
            {"status": "ready", "checks": {"neo4j": "ok"}},
        ),
        ("GET", "/api/overview-stats"): (
            200,
            {"node_count": 3, "edge_count": 2},
        ),
        ("GET", "/api/knowledge-graph/raw"): (
            200,
            {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
                "total_nodes": 3,
                "total_edges": 2,
                "returned_nodes": 3,
                "returned_edges": 2,
                "truncated": False,
            },
        ),
        ("GET", "/api/learning-paths/communities"): (200, unavailable),
        ("GET", "/api/learning-paths/chapters"): (200, unavailable),
        ("GET", "/api/placement-test"): (404, {"error": "not_found"}),
        ("POST", "/api/placement-test/submit"): (404, {"error": "not_found"}),
        ("POST", "/api/node/complete"): (404, {"error": "not_found"}),
    }


class FakeTransport:
    def __init__(self, payloads: dict[tuple[str, str], tuple[int, object]]) -> None:
        self.payloads = payloads
        self.calls: list[Endpoint] = []

    def __call__(self, _base_url: str, endpoint: Endpoint, _timeout: int) -> HttpResult:
        self.calls.append(endpoint)
        target = endpoint.body.get("target_node") if isinstance(endpoint.body, dict) else None
        key = (endpoint.method, endpoint.path, target)
        status, payload = self.payloads.get(key, self.payloads[(endpoint.method, endpoint.path)])
        return HttpResult(status=status, payload=payload)


def run_http_smoke(payloads: dict[tuple[str, str], tuple[int, object]]):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            status, payload = payloads[(self.command, self.path)]
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._respond()

        def do_POST(self) -> None:
            self._respond()

        def log_message(self, _format, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        return run_smoke(f"http://{host}:{port}", 1, False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class SmokeSemanticTests(unittest.TestCase):
    def test_clean_contract_passes_through_real_http_transport(self) -> None:
        result = run_http_smoke(clean_payloads())

        self.assertEqual([], result.failures)

    def test_http_mock_rejects_empty_array_and_fake_success(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/learning-paths/communities")] = (200, [])
        payloads[("POST", "/api/node/complete")] = (200, {"success": True})

        result = run_http_smoke(payloads)

        self.assertTrue(any("JSON_OBJECT_REQUIRED" in item for item in result.failures))
        self.assertTrue(any("REMOVED_ROUTE_STILL_ACTIVE" in item for item in result.failures))

    def test_clean_unavailable_analysis_contract_passes(self) -> None:
        transport = FakeTransport(clean_payloads())

        result = run_smoke("http://example.invalid", 1, False, transport=transport)

        self.assertEqual([], result.failures)
        self.assertFalse(any(endpoint.requires_llm for endpoint in transport.calls))

    def test_http_200_empty_groups_is_a_hard_failure(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/learning-paths/communities")] = (
            200,
            {"status": "ok", "analysis_node_count": 3, "groups": []},
        )

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("EMPTY_ANALYSIS_GROUPS" in item for item in result.failures))

    def test_partial_analysis_and_target_scoped_contracts_pass(self) -> None:
        payloads = clean_payloads()
        partial = {
            "status": "partial",
            "analysis_state": "partial",
            "analysis_node_count": 2,
            "community_node_count": 3,
            "analysis_coverage": 2 / 3,
            "groups": [{"nodes": [
                {"name": "x", "outDegree": 1, "layer": 0},
                {"name": "y", "outDegree": 0, "layer": 1},
            ]}],
        }
        payloads[("GET", "/api/learning-paths/communities")] = (200, partial)
        payloads[("GET", "/api/learning-paths/chapters")] = (200, partial)
        payloads[("POST", "/api/learning-paths/plan")] = (500, {"error": "unexpected"})
        payloads[("POST", "/api/learning-paths/plan", "x")] = (200, {
            "status": "ok",
            "analysis_state": "complete",
            "total": 2,
            "items": [
                {"name": "x", "outDegree": 1, "layer": 0},
                {"name": "y", "outDegree": 0, "layer": 1},
            ],
            "target_scope": {
                "analysis_state": "complete",
                "analysis_node_count": 2,
                "community_node_count": 2,
            },
        })
        payloads[("POST", "/api/learning-paths/plan", "z")] = (200, {
            "status": "analysis_unavailable",
            "items": [],
            "path": [],
            "analysis_node_count": 0,
            "target_scope": {
                "analysis_state": "unavailable",
                "analysis_node_count": 0,
                "community_node_count": 1,
            },
        })

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
            analyzed_target="x",
            unanalyzed_target="z",
        )

        self.assertEqual([], result.failures)

    def test_http_200_bare_empty_array_is_a_hard_failure(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/learning-paths/communities")] = (200, [])

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("JSON_OBJECT_REQUIRED" in item for item in result.failures))

    def test_http_200_all_null_analysis_is_a_hard_failure(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/learning-paths/communities")] = (
            200,
            {
                "status": "ok",
                "analysis_node_count": 1,
                "groups": [{"nodes": [{"name": "x", "outDegree": None, "layer": None}]}],
            },
        )

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("NULL_ANALYSIS_VALUE" in item for item in result.failures))

    def test_http_200_all_zero_analysis_is_a_hard_failure(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/learning-paths/communities")] = (
            200,
            {
                "status": "ok",
                "analysis_node_count": 2,
                "groups": [
                    {
                        "nodes": [
                            {"name": "x", "outDegree": 0, "layer": 0},
                            {"name": "y", "outDegree": 0, "layer": 0},
                        ]
                    }
                ],
            },
        )
        payloads[("POST", "/api/learning-paths/plan")] = (
            200,
            {
                "status": "ok",
                "path": [
                    {"name": "x", "outDegree": 0, "layer": 0},
                    {"name": "y", "outDegree": 0, "layer": 0},
                ],
            },
        )

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("ALL_ZERO_ANALYSIS_VALUES" in item for item in result.failures))
        self.assertTrue(any("ALL_ZERO_PLAN_VALUES" in item for item in result.failures))

    def test_target_only_plan_is_a_hard_failure(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/learning-paths/communities")] = (
            200,
            {
                "status": "ok",
                "analysis_node_count": 2,
                "groups": [
                    {
                        "nodes": [
                            {"name": "x", "outDegree": 1, "layer": 0},
                            {"name": "y", "outDegree": 0, "layer": 1},
                        ]
                    }
                ],
            },
        )
        payloads[("POST", "/api/learning-paths/plan")] = (
            200,
            {"status": "ok", "path": [{"name": "x", "outDegree": 1, "layer": 0}]},
        )

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("PLAN_TARGET_ONLY_OR_EMPTY" in item for item in result.failures))

    def test_removed_route_fake_success_is_a_hard_failure(self) -> None:
        payloads = clean_payloads()
        payloads[("POST", "/api/node/complete")] = (200, {"success": True})

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("REMOVED_ROUTE_STILL_ACTIVE" in item for item in result.failures))

    def test_raw_graph_must_match_overview_counts(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/overview-stats")] = (
            200,
            {"node_count": 4, "edge_count": 2},
        )

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("RAW_OVERVIEW_NODE_MISMATCH" in item for item in result.failures))

    def test_ready_requires_explicit_neo4j_check(self) -> None:
        payloads = clean_payloads()
        payloads[("GET", "/api/health/ready")] = (200, {"status": "ready"})

        result = run_smoke(
            "http://example.invalid",
            1,
            False,
            transport=FakeTransport(payloads),
        )

        self.assertTrue(any("READY_NEO4J_NOT_CONFIRMED" in item for item in result.failures))

    def test_llm_endpoints_are_opt_in(self) -> None:
        self.assertFalse(any(endpoint.requires_llm for endpoint in build_endpoints(False)))
        llm_endpoints = [endpoint for endpoint in build_endpoints(True) if endpoint.requires_llm]
        self.assertTrue(llm_endpoints)
        self.assertTrue(all(endpoint.timeout <= 30 for endpoint in llm_endpoints))


if __name__ == "__main__":
    unittest.main()
