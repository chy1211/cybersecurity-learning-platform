from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:5000"
DEFAULT_TIMEOUT = 10
LLM_TIMEOUT = 30
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    validator: str
    body: dict | None = None
    requires_llm: bool = False
    timeout: int = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class HttpResult:
    status: int | str
    payload: object | None = None
    error: str | None = None


@dataclass(frozen=True)
class SmokeResult:
    failures: list[str]
    checked: int


Transport = Callable[[str, Endpoint, int], HttpResult]


def build_endpoints(include_llm: bool) -> list[Endpoint]:
    endpoints = [
        Endpoint("GET", "/api/health/live", "live"),
        Endpoint("GET", "/api/health/ready", "ready"),
        Endpoint("GET", "/api/overview-stats", "overview"),
        Endpoint("GET", "/api/knowledge-graph/raw", "raw_graph"),
        Endpoint("GET", "/api/learning-paths/communities", "analysis"),
        Endpoint("GET", "/api/learning-paths/chapters", "analysis"),
        Endpoint("GET", "/api/placement-test", "removed"),
        Endpoint("POST", "/api/placement-test/submit", "removed", {}),
        Endpoint("POST", "/api/node/complete", "removed", {}),
    ]
    if include_llm:
        endpoints.append(
            Endpoint(
                "POST",
                "/api/chat",
                "llm",
                {"message": "What is information security?"},
                requires_llm=True,
                timeout=LLM_TIMEOUT,
            )
        )
    return endpoints


def _decode_payload(raw: bytes) -> tuple[object | None, str | None]:
    if not raw:
        return None, "EMPTY_RESPONSE_BODY"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "INVALID_JSON_RESPONSE"


def call(base_url: str, endpoint: Endpoint, timeout: int) -> HttpResult:
    data = None
    headers = {}
    if endpoint.body is not None:
        data = json.dumps(endpoint.body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        base_url + quote(endpoint.path, safe="/?=&"),
        data=data,
        headers=headers,
        method=endpoint.method,
    )
    request_timeout = max(timeout, endpoint.timeout)
    try:
        with urlopen(request, timeout=request_timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return HttpResult(response.status, error="RESPONSE_BODY_TOO_LARGE")
            payload, error = _decode_payload(raw)
            return HttpResult(response.status, payload, error)
    except HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return HttpResult(exc.code, error="RESPONSE_BODY_TOO_LARGE")
        payload, error = _decode_payload(raw)
        return HttpResult(exc.code, payload, error)
    except URLError as exc:
        return HttpResult("URLERR", error=type(exc.reason).__name__)
    except TimeoutError:
        return HttpResult("TIMEOUT", error="TIMEOUT")


def _is_success(status: int | str) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def _dict_payload(result: HttpResult) -> dict | None:
    return result.payload if isinstance(result.payload, dict) else None


def _validate_live(payload: dict) -> list[str]:
    if str(payload.get("status", "")).lower() not in {"live", "ok", "healthy"}:
        return ["LIVE_STATUS_INVALID"]
    return []


def _validate_ready(payload: dict) -> list[str]:
    errors = []
    if str(payload.get("status", "")).lower() not in {"ready", "ok", "healthy"}:
        errors.append("READY_STATUS_INVALID")
    neo4j = payload.get("neo4j")
    if neo4j is None and isinstance(payload.get("checks"), dict):
        neo4j = payload["checks"].get("neo4j")
    accepted = {True, "ok", "ready", "connected", "healthy"}
    if neo4j not in accepted:
        errors.append("READY_NEO4J_NOT_CONFIRMED")
    return errors


def _validate_overview(payload: dict) -> list[str]:
    errors = []
    for key in ("node_count", "edge_count"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"OVERVIEW_{key.upper()}_INVALID")
    return errors


def _validate_raw_graph(payload: dict) -> list[str]:
    errors = []
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list):
        errors.append("RAW_NODES_NOT_LIST")
        nodes = []
    if not isinstance(edges, list):
        errors.append("RAW_EDGES_NOT_LIST")
        edges = []
    counts = {}
    for key in ("total_nodes", "total_edges", "returned_nodes", "returned_edges"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"RAW_{key.upper()}_INVALID")
        else:
            counts[key] = value
    if payload.get("truncated") not in {True, False}:
        errors.append("RAW_TRUNCATED_NOT_BOOLEAN")
    if counts.get("total_nodes", 0) <= 0 or counts.get("total_edges", 0) <= 0:
        errors.append("RAW_GRAPH_EMPTY")
    if "returned_nodes" in counts and counts["returned_nodes"] != len(nodes):
        errors.append("RAW_RETURNED_NODE_COUNT_MISMATCH")
    if "returned_edges" in counts and counts["returned_edges"] != len(edges):
        errors.append("RAW_RETURNED_EDGE_COUNT_MISMATCH")
    if counts.get("returned_nodes", 0) > counts.get("total_nodes", 0):
        errors.append("RAW_RETURNED_NODES_EXCEED_TOTAL")
    if counts.get("returned_edges", 0) > counts.get("total_edges", 0):
        errors.append("RAW_RETURNED_EDGES_EXCEED_TOTAL")
    if payload.get("truncated") is False and (
        counts.get("returned_nodes") != counts.get("total_nodes")
        or counts.get("returned_edges") != counts.get("total_edges")
    ):
        errors.append("RAW_SILENT_TRUNCATION")
    return errors


def _analysis_nodes(payload: dict) -> list[dict]:
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return []
    return [node for group in groups if isinstance(group, dict)
            for node in group.get("nodes", []) if isinstance(node, dict)]


def _validate_analysis(payload: dict) -> list[str]:
    status = payload.get("status")
    if status == "analysis_unavailable":
        errors = []
        if payload.get("analysis_node_count") != 0:
            errors.append("UNAVAILABLE_ANALYSIS_COUNT_NOT_ZERO")
        if payload.get("groups") not in (None, []):
            errors.append("UNAVAILABLE_ANALYSIS_GROUPS_NOT_EMPTY")
        return errors
    if status not in {"ok", "partial"}:
        return ["ANALYSIS_STATUS_INVALID"]
    errors = []
    analyzed = payload.get("analysis_node_count")
    eligible = payload.get("community_node_count")
    if not isinstance(analyzed, int) or analyzed <= 0:
        errors.append("ANALYSIS_COUNT_INVALID")
    if (
        not isinstance(eligible, int)
        or eligible <= 0
        or not isinstance(analyzed, int)
        or analyzed > eligible
    ):
        errors.append("ANALYSIS_ELIGIBLE_COUNT_INVALID")
    if status == "partial" and (
        payload.get("analysis_state") != "partial"
        or not isinstance(analyzed, int)
        or not isinstance(eligible, int)
        or analyzed >= eligible
    ):
        errors.append("PARTIAL_ANALYSIS_STATE_INVALID")
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        errors.append("EMPTY_ANALYSIS_GROUPS")
    nodes = _analysis_nodes(payload)
    if not nodes:
        errors.append("EMPTY_ANALYSIS_NODES")
    if any(node.get("outDegree") is None or node.get("layer") is None for node in nodes):
        errors.append("NULL_ANALYSIS_VALUE")
    if all(node.get("outDegree") == 0 and node.get("layer") == 0 for node in nodes):
        errors.append("ALL_ZERO_ANALYSIS_VALUES")
    return errors


def _validate_plan(payload: dict) -> list[str]:
    status = payload.get("status")
    if status != "ok":
        return ["PLAN_STATUS_INVALID"]
    path = payload.get("items", payload.get("path"))
    if not isinstance(path, list) or len(path) < 2:
        return ["PLAN_TARGET_ONLY_OR_EMPTY"]
    nodes = [node for node in path if isinstance(node, dict)]
    errors = []
    if len(nodes) != len(path):
        errors.append("PLAN_NODE_INVALID")
    if any(node.get("outDegree") is None or node.get("layer") is None for node in nodes):
        errors.append("NULL_PLAN_ANALYSIS_VALUE")
    if nodes and all(node.get("outDegree") == 0 and node.get("layer") == 0 for node in nodes):
        errors.append("ALL_ZERO_PLAN_VALUES")
    scope = payload.get("target_scope")
    if not isinstance(scope, dict) or scope.get("analysis_state") != "complete":
        errors.append("PLAN_TARGET_SCOPE_NOT_COMPLETE")
    elif (
        scope.get("analysis_node_count") != scope.get("community_node_count")
        or not isinstance(scope.get("analysis_node_count"), int)
        or scope["analysis_node_count"] <= 0
    ):
        errors.append("PLAN_TARGET_SCOPE_COVERAGE_INVALID")
    if not isinstance(payload.get("total"), int) or payload["total"] <= 0:
        errors.append("PLAN_TOTAL_INVALID")
    return errors


def _validate_unavailable_plan(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "analysis_unavailable":
        errors.append("UNAVAILABLE_PLAN_STATUS_INVALID")
    if payload.get("items") not in (None, []) or payload.get("path") not in (None, []):
        errors.append("UNAVAILABLE_PLAN_RESULTS_NOT_EMPTY")
    if payload.get("analysis_node_count") != 0:
        errors.append("UNAVAILABLE_PLAN_ANALYSIS_COUNT_NOT_ZERO")
    scope = payload.get("target_scope")
    if not isinstance(scope, dict) or scope.get("analysis_state") != "unavailable":
        errors.append("UNAVAILABLE_TARGET_SCOPE_STATE_INVALID")
    elif scope.get("analysis_node_count") != 0:
        errors.append("UNAVAILABLE_TARGET_SCOPE_COUNT_NOT_ZERO")
    return errors


def _validate_llm(payload: dict) -> list[str]:
    errors = []
    if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        errors.append("LLM_ANSWER_EMPTY")
    if not isinstance(payload.get("evidence"), list):
        errors.append("LLM_EVIDENCE_NOT_LIST")
    return errors


def validate_response(endpoint: Endpoint, result: HttpResult) -> list[str]:
    if endpoint.validator == "removed":
        return [] if result.status == 404 else ["REMOVED_ROUTE_STILL_ACTIVE"]
    if not _is_success(result.status):
        return [f"HTTP_STATUS_{result.status}"]
    if result.error:
        return [result.error]
    payload = _dict_payload(result)
    if payload is None:
        return ["JSON_OBJECT_REQUIRED"]
    validators = {
        "live": _validate_live,
        "ready": _validate_ready,
        "overview": _validate_overview,
        "raw_graph": _validate_raw_graph,
        "analysis": _validate_analysis,
        "plan": _validate_plan,
        "plan_unavailable": _validate_unavailable_plan,
        "llm": _validate_llm,
    }
    return validators[endpoint.validator](payload)


def _find_plan_target(analysis: dict) -> str | None:
    groups = analysis.get("groups")
    if not isinstance(groups, list):
        return None
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("nodes"), list):
            continue
        nodes = group["nodes"]
        if len(nodes) < 2:
            continue
        name = nodes[0].get("name") if isinstance(nodes[0], dict) else None
        if isinstance(name, str) and name:
            return name
    return None


def _cross_validate_counts(overview: dict, raw: dict) -> list[str]:
    errors = []
    if overview.get("node_count") != raw.get("total_nodes"):
        errors.append("RAW_OVERVIEW_NODE_MISMATCH")
    if overview.get("edge_count") != raw.get("total_edges"):
        errors.append("RAW_OVERVIEW_EDGE_MISMATCH")
    return errors


def run_smoke(
    base_url: str,
    timeout: int,
    include_llm: bool,
    *,
    transport: Transport = call,
    analyzed_target: str | None = None,
    unanalyzed_target: str | None = None,
) -> SmokeResult:
    failures: list[str] = []
    checked = 0
    payloads: dict[str, dict] = {}
    for endpoint in build_endpoints(include_llm):
        result = transport(base_url, endpoint, timeout)
        checked += 1
        for error in validate_response(endpoint, result):
            failures.append(f"{endpoint.method} {endpoint.path} {error}")
        if _is_success(result.status) and isinstance(result.payload, dict):
            payloads[endpoint.path] = result.payload

    overview = payloads.get("/api/overview-stats")
    raw = payloads.get("/api/knowledge-graph/raw")
    if overview is not None and raw is not None:
        failures.extend(_cross_validate_counts(overview, raw))

    communities = payloads.get("/api/learning-paths/communities")
    if communities is not None and communities.get("status") in {"ok", "partial"}:
        target = analyzed_target or _find_plan_target(communities)
        if target is None:
            failures.append("PLAN_TARGET_UNAVAILABLE")
        else:
            endpoint = Endpoint(
                "POST",
                "/api/learning-paths/plan",
                "plan",
                {"target_node": target, "learned_nodes": [], "mode": "community"},
            )
            result = transport(base_url, endpoint, timeout)
            checked += 1
            for error in validate_response(endpoint, result):
                failures.append(f"{endpoint.method} {endpoint.path} {error}")
        if unanalyzed_target:
            endpoint = Endpoint(
                "POST",
                "/api/learning-paths/plan",
                "plan_unavailable",
                {"target_node": unanalyzed_target, "learned_nodes": [], "mode": "community"},
            )
            result = transport(base_url, endpoint, timeout)
            checked += 1
            for error in validate_response(endpoint, result):
                failures.append(f"{endpoint.method} {endpoint.path} {error}")
    return SmokeResult(failures=failures, checked=checked)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Semantic smoke test for the platform API.")
    parser.add_argument("--backend-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Opt in to the bounded chat integration check (disabled by default).",
    )
    parser.add_argument("--analyzed-target", help="Known target in a fully analyzed community.")
    parser.add_argument("--unanalyzed-target", help="Known target in an unanalyzed community.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_smoke(
        args.backend_url.rstrip("/"),
        args.timeout,
        args.include_llm,
        analyzed_target=args.analyzed_target,
        unanalyzed_target=args.unanalyzed_target,
    )
    print(f"checked={result.checked}")
    print(f"failures={len(result.failures)}")
    for failure in result.failures:
        print(f"FAIL {failure}")
    if result.failures:
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
