from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from smoke_test_platform import run_smoke


def request_json(base_url: str, method: str, path: str, body=None, timeout: int = 30):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-migration API and semantic smoke acceptance.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:5000")
    parser.add_argument("--targets-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    targets = json.loads(args.targets_json.read_text(encoding="utf-8"))["api_targets"]
    evidence = {"status": "PASS", "endpoints": {}, "targets": targets}

    for path in (
        "/api/health/live",
        "/api/health/ready",
        "/api/overview-stats",
        "/api/knowledge-graph/raw",
        "/api/learning-paths/communities",
    ):
        status, payload = request_json(args.backend_url, "GET", path)
        require(status == 200, f"{path} HTTP {status}")
        evidence["endpoints"][path] = {"http_status": status}
        if path == "/api/health/live":
            require(payload.get("status") == "live", "live status mismatch")
            evidence["endpoints"][path]["status"] = payload.get("status")
        elif path == "/api/health/ready":
            require(payload.get("status") == "ready", "ready status mismatch")
            require(payload.get("neo4j") == "connected", "Neo4j readiness mismatch")
            evidence["endpoints"][path].update({"status": payload.get("status"), "neo4j": payload.get("neo4j")})
        elif path == "/api/overview-stats":
            evidence["overview"] = payload
        elif path == "/api/knowledge-graph/raw":
            evidence["raw"] = {
                key: payload.get(key)
                for key in ("total_nodes", "total_edges", "returned_nodes", "returned_edges", "truncated")
            }
        else:
            require(payload.get("status") == "partial", "community analysis status is not partial")
            require(payload.get("analysis_state") == "partial", "community analysis_state is not partial")
            require(payload.get("analysis_node_count") == 2375, "analysis_node_count mismatch")
            require(payload.get("community_node_count") == 2554, "community_node_count mismatch")
            evidence["community_analysis"] = {
                key: payload.get(key)
                for key in (
                    "status", "analysis_state", "analysis_node_count",
                    "community_node_count", "analysis_coverage",
                )
            }

    require(evidence["overview"]["node_count"] == evidence["raw"]["total_nodes"], "overview/raw node mismatch")
    require(evidence["overview"]["edge_count"] == evidence["raw"]["total_edges"], "overview/raw edge mismatch")

    plan_evidence = {}
    for label in ("analyzed", "unanalyzed"):
        status, payload = request_json(
            args.backend_url,
            "POST",
            "/api/learning-paths/plan",
            {"target_node": targets[label]["name"], "learned_nodes": [], "mode": "community"},
        )
        require(status == 200, f"{label} plan HTTP {status}")
        scope = payload.get("target_scope") or {}
        if label == "analyzed":
            require(payload.get("status") == "ok", "analyzed target status mismatch")
            require(payload.get("analysis_state") == "complete", "analyzed target state mismatch")
            require(isinstance(payload.get("items"), list) and payload["items"], "analyzed target items empty")
            require(isinstance(payload.get("total"), int) and payload["total"] > 0, "analyzed target total invalid")
            require(scope.get("analysis_state") == "complete", "analyzed target scope state mismatch")
            require(scope.get("analysis_node_count") == scope.get("community_node_count"), "analyzed target scope incomplete")
        else:
            require(payload.get("status") == "analysis_unavailable", "unanalyzed target status mismatch")
            require(payload.get("items") in (None, []), "unanalyzed target items not empty")
            require(payload.get("path") in (None, []), "unanalyzed target path not empty")
            require(payload.get("analysis_node_count") == 0, "unanalyzed target analysis count mismatch")
            require(scope.get("analysis_state") == "unavailable", "unanalyzed target scope state mismatch")
            require(scope.get("analysis_node_count") == 0, "unanalyzed target scope count mismatch")
        plan_evidence[label] = {
            "http_status": status,
            "target": targets[label]["name"],
            "status": payload.get("status"),
            "analysis_state": payload.get("analysis_state"),
            "item_count": len(payload.get("items") or []),
            "total": payload.get("total"),
            "analysis_node_count": payload.get("analysis_node_count"),
            "community_node_count": payload.get("community_node_count"),
            "target_scope": scope,
        }
    evidence["plans"] = plan_evidence

    smoke = run_smoke(
        args.backend_url,
        10,
        False,
        analyzed_target=targets["analyzed"]["name"],
        unanalyzed_target=targets["unanalyzed"]["name"],
    )
    evidence["semantic_smoke"] = {"checked": smoke.checked, "failures": smoke.failures}
    require(not smoke.failures, f"semantic smoke failures: {smoke.failures}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
