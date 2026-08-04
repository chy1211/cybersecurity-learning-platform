"""Fixed-embedding semantic index used by the B4 entity linker.

The evaluated LLMs never participate in this component.  The index uses one
explicit embedding model, records that model in its own cache, and exposes a
deterministic top-k search function for the gated semantic-linking step.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


DEFAULT_EMBEDDING_MODEL = "text-embedding-embeddinggemma-300m-qat"
DEFAULT_EMBEDDING_BASE_URL = os.getenv(
    "EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1"
).rstrip("/")
CACHE_SCHEMA_VERSION = "b4-semantic-index-v1"


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class EmbeddingEndpointError(RuntimeError):
    """Raised when the fixed embedding endpoint cannot produce valid vectors."""


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


RequestFunction = Callable[..., Any]


class OpenAIEmbeddingClient:
    """Small OpenAI-compatible client with bounded retries and no fallback."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_EMBEDDING_BASE_URL,
        model: str = DEFAULT_EMBEDDING_MODEL,
        timeout: float = 30.0,
        retries: int = 3,
        request_fn: RequestFunction | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self._request_fn = request_fn
        self._sleep_fn = sleep_fn

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = [str(text) for text in texts]
        if not values:
            return []
        if self._request_fn is None:
            import requests

            request_fn = requests.post
        else:
            request_fn = self._request_fn

        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model, "input": values}
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = request_fn(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout,
                )
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                elif getattr(response, "status_code", 200) >= 400:
                    raise EmbeddingEndpointError(
                        f"embedding endpoint returned HTTP {response.status_code}"
                    )
                body = response.json()
                data = body.get("data")
                if not isinstance(data, list) or len(data) != len(values):
                    raise EmbeddingEndpointError(
                        "embedding response data length does not match input"
                    )
                ordered: list[list[float] | None] = [None] * len(values)
                for item in data:
                    index = int(item.get("index", 0))
                    vector = item.get("embedding")
                    if not 0 <= index < len(values) or not isinstance(vector, list):
                        raise EmbeddingEndpointError(
                            "embedding response contains an invalid item"
                        )
                    ordered[index] = [float(value) for value in vector]
                if any(vector is None for vector in ordered):
                    raise EmbeddingEndpointError(
                        "embedding response omitted one or more indexes"
                    )
                return [vector for vector in ordered if vector is not None]
            except Exception as exc:  # bounded retry, then hard failure
                last_error = exc
                if attempt + 1 < self.retries:
                    self._sleep_fn(2**attempt)
        raise EmbeddingEndpointError(
            f"fixed embedding endpoint failed after {self.retries} attempts"
        ) from last_error


@dataclass(frozen=True)
class SemanticIndex:
    nodes: tuple[dict[str, Any], ...]
    vectors: Mapping[str, tuple[float, ...]]
    model: str

    def search(self, text: str, query_vector: Sequence[float], top_k: int) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        candidates: list[dict[str, Any]] = []
        for node in self.nodes:
            vector = self.vectors[node["element_id"]]
            candidates.append(
                {
                    "element_id": node["element_id"],
                    "name": node["name"],
                    "score": cosine_similarity(query_vector, vector),
                    **({"type": node["type"]} if node.get("type") is not None else {}),
                }
            )
        candidates.sort(
            key=lambda item: (-item["score"], item["name"], item["element_id"])
        )
        return candidates[:top_k]

    def provider(self, client: EmbeddingProvider) -> Callable[[str, int], Iterable[Mapping[str, Any]]]:
        if client.model != self.model:
            raise ValueError(
                f"embedding client model {client.model!r} does not match index {self.model!r}"
            )

        def search(text: str, top_k: int) -> Iterable[Mapping[str, Any]]:
            vectors = client.embed([text])
            if len(vectors) != 1:
                raise EmbeddingEndpointError("query embedding response is invalid")
            return self.search(text, vectors[0], top_k)

        return search


def _copy_node(node: Mapping[str, Any]) -> dict[str, Any]:
    element_id = str(node.get("element_id") or node.get("id") or "").strip()
    name = str(node.get("name") or "").strip()
    if not element_id or not name:
        raise ValueError("semantic index nodes need element_id and name")
    result = {"element_id": element_id, "name": name}
    if node.get("type") is not None:
        result["type"] = str(node["type"])
    return result


def _read_cache(cache_path: Path, model: str) -> dict[str, Any]:
    if not cache_path.exists():
        return {"nodes": {}}
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise ValueError("semantic index cache schema does not match B4")
    if payload.get("embedding_model") != model:
        raise ValueError("semantic index cache was built with another embedding model")
    nodes = payload.get("nodes", {})
    if not isinstance(nodes, dict):
        raise ValueError("semantic index cache nodes must be an object")
    return payload


def build_semantic_index(
    nodes: Iterable[Mapping[str, Any]],
    *,
    client: EmbeddingProvider,
    cache_path: Path,
    rebuild: bool = False,
) -> SemanticIndex:
    """Build or reuse a cache without changing the repository's legacy cache."""

    copied_nodes = tuple(sorted((_copy_node(node) for node in nodes), key=lambda item: item["element_id"]))
    node_ids = [node["element_id"] for node in copied_nodes]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("semantic index node IDs must be unique")

    cache = {"nodes": {}} if rebuild else _read_cache(cache_path, client.model)
    cached_nodes = cache.get("nodes", {})
    vectors: dict[str, tuple[float, ...]] = {}
    missing: list[dict[str, Any]] = []
    for node in copied_nodes:
        cached = cached_nodes.get(node["element_id"])
        if (
            isinstance(cached, dict)
            and cached.get("name") == node["name"]
            and isinstance(cached.get("embedding"), list)
        ):
            vectors[node["element_id"]] = tuple(float(value) for value in cached["embedding"])
        else:
            missing.append(node)

    if missing:
        embedded = client.embed([node["name"] for node in missing])
        if len(embedded) != len(missing):
            raise EmbeddingEndpointError("node embedding count does not match nodes")
        for node, vector in zip(missing, embedded):
            if not vector:
                raise EmbeddingEndpointError(f"empty embedding returned for {node['name']!r}")
            vectors[node["element_id"]] = tuple(float(value) for value in vector)

    dimensions = {len(vector) for vector in vectors.values()}
    if len(dimensions) > 1:
        raise ValueError("semantic index contains inconsistent embedding dimensions")

    cache_payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "embedding_model": client.model,
        "nodes": {
            node["element_id"]: {
                "name": node["name"],
                "embedding": list(vectors[node["element_id"]]),
            }
            for node in copied_nodes
        },
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return SemanticIndex(copied_nodes, vectors, client.model)

