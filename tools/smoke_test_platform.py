from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote


DEFAULT_BASE_URL = "http://127.0.0.1:5000"
DEFAULT_TIMEOUT = 20


@dataclass
class Endpoint:
    method: str
    path: str
    body: dict | None = None
    requires_neo4j: bool = False
    requires_llm: bool = False
    timeout: int = DEFAULT_TIMEOUT


ENDPOINTS = [
    Endpoint("GET", "/api/health"),
    Endpoint("GET", "/api/placement-test"),
    Endpoint("POST", "/api/placement-test/submit", {}),
    Endpoint("GET", "/api/mistakes"),
    Endpoint("GET", "/api/user-progress"),
    Endpoint("POST", "/api/user-progress/toggle", {"node_id": "__smoke_test_node__"}),
    Endpoint("POST", "/api/user-progress/toggle", {"node_id": "__smoke_test_node__"}),
    Endpoint("POST", "/api/node/complete", {}),
    Endpoint("GET", "/api/overview-stats", requires_neo4j=True),
    Endpoint("GET", "/api/chapters", requires_neo4j=True),
    Endpoint("GET", "/api/communities", requires_neo4j=True),
    Endpoint("GET", "/api/skill-tree", requires_neo4j=True),
    Endpoint("GET", "/api/knowledge-graph/raw", requires_neo4j=True),
    Endpoint("GET", "/api/learning-paths/communities", requires_neo4j=True),
    Endpoint("GET", "/api/learning-paths/chapters", requires_neo4j=True),
    Endpoint("GET", "/api/learning-paths/search?q=安全&mode=community", requires_neo4j=True),
    Endpoint("POST", "/api/learning-paths/plan", {"target_node": "安全網路", "learned_nodes": [], "mode": "community"}, requires_neo4j=True),
    Endpoint("POST", "/api/chat", {"message": "什麼是資訊安全？"}, requires_neo4j=True, requires_llm=True, timeout=90),
    Endpoint("POST", "/api/quiz/generate", {"node_id": "資訊安全"}, requires_neo4j=True, requires_llm=True, timeout=90),
]


def call(base_url: str, endpoint: Endpoint, timeout: int) -> tuple[int | str, str]:
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
            body = response.read(500).decode("utf-8", "replace")
            return response.status, body
    except HTTPError as exc:
        body = exc.read(500).decode("utf-8", "replace")
        return exc.code, body
    except URLError as exc:
        return "URLERR", str(exc.reason)
    except TimeoutError as exc:
        return "TIMEOUT", str(exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test platform API endpoints.")
    parser.add_argument("--backend-url", default=DEFAULT_BASE_URL, help="Base URL for the Flask backend.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Minimum request timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.backend_url.rstrip("/")
    hard_failures = 0
    soft_failures = 0
    for endpoint in ENDPOINTS:
        status, body = call(base_url, endpoint, args.timeout)
        label = f"{endpoint.method} {endpoint.path}"
        needs = []
        if endpoint.requires_neo4j:
            needs.append("neo4j")
        if endpoint.requires_llm:
            needs.append("llm")
        dependency = f" ({'+'.join(needs)})" if needs else ""
        print(f"{status} {label}{dependency} :: {body[:220].replace(chr(10), ' ')}")

        if isinstance(status, int) and 200 <= status < 300:
            continue
        if endpoint.requires_neo4j or endpoint.requires_llm:
            soft_failures += 1
        else:
            hard_failures += 1

    print(f"hard_failures={hard_failures}")
    print(f"soft_dependency_failures={soft_failures}")
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
