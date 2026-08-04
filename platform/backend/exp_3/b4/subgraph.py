"""Deterministic bounded subgraph expansion for B4 Step 3."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping


EdgeFetcher = Callable[[list[str], list[str]], Iterable[Mapping[str, Any]]]


def _merge_list(left: list[Any], right: Iterable[Any]) -> list[Any]:
    return sorted(set(left).union(right), key=str)


def expand_subgraph(
    seeds: Iterable[Mapping[str, Any]],
    relations: Iterable[str],
    fetch_edges: EdgeFetcher,
    *,
    relations_by_node: Mapping[str, Iterable[str]] | None = None,
    max_hops: int = 2,
    max_triples_per_node: int = 50,
    max_evidence_per_question: int = 100,
) -> dict[str, Any]:
    """Expand both directions with fixed hop and evidence budgets.

    ``fetch_edges`` must return edges incident to the requested node IDs and
    restricted to the supplied relation allow-list.  Each seed carries its
    own source provenance; expansion carries that provenance forward.
    """

    if max_hops < 1:
        raise ValueError("max_hops must be >= 1")
    relation_set = sorted({str(item).strip() for item in relations if str(item).strip()})
    relation_map = {
        str(node_id): {
            str(item).strip() for item in node_relations if str(item).strip()
        }
        for node_id, node_relations in (relations_by_node or {}).items()
    }
    frontier: dict[str, dict[str, Any]] = {}
    for seed in seeds:
        node_id = str(seed.get("element_id") or seed.get("id") or "").strip()
        if not node_id:
            raise ValueError("each seed needs element_id")
        current = frontier.setdefault(
            node_id,
            {
                "seed_node_ids": [],
                "subclaim_ids": [],
                "origins": [],
                "link_statuses": [],
            },
        )
        current["seed_node_ids"] = _merge_list(
            current["seed_node_ids"], [node_id, *seed.get("seed_node_ids", [])]
        )
        current["subclaim_ids"] = _merge_list(
            current["subclaim_ids"], seed.get("subclaim_ids", [])
        )
        current["origins"] = _merge_list(current["origins"], seed.get("origins", []))
        current["link_statuses"] = _merge_list(
            current["link_statuses"], seed.get("link_statuses", [])
        )

    evidence: dict[tuple[str, str, str], dict[str, Any]] = {}
    per_node_counts: defaultdict[str, int] = defaultdict(int)
    visited_nodes = set(frontier)
    truncated_by_node = False

    for hop in range(1, max_hops + 1):
        if not frontier or not relation_set:
            break
        frontier_ids = sorted(frontier)
        frontier_relations = set(relation_set)
        if hop == 1 and relation_map:
            frontier_relations = set().union(
                *(relation_map.get(node_id, set()) for node_id in frontier_ids)
            )
        if not frontier_relations:
            break
        next_frontier: dict[str, dict[str, Any]] = {}
        raw_edges = sorted(
            (dict(edge) for edge in fetch_edges(frontier_ids, sorted(frontier_relations))),
            key=lambda edge: (
                str(edge.get("head_id", "")),
                str(edge.get("relation", "")),
                str(edge.get("tail_id", "")),
            ),
        )
        for edge in raw_edges:
            head_id = str(edge.get("head_id") or "").strip()
            tail_id = str(edge.get("tail_id") or "").strip()
            relation = str(edge.get("relation") or "").strip()
            if not head_id or not tail_id or not relation:
                continue
            if relation not in relation_set:
                raise ValueError(f"edge contains unselected relation: {relation}")
            source_ids = [node_id for node_id in frontier_ids if node_id in {head_id, tail_id}]
            for source_id in source_ids:
                if hop == 1 and relation_map.get(source_id) is not None:
                    if relation not in relation_map[source_id]:
                        continue
                if per_node_counts[source_id] >= max_triples_per_node:
                    truncated_by_node = True
                    continue
                provenance = frontier[source_id]
                key = (head_id, relation, tail_id)
                record = evidence.get(key)
                if record is None:
                    record = {
                        "head_id": head_id,
                        "head": str(edge.get("head") or head_id),
                        "relation": relation,
                        "tail_id": tail_id,
                        "tail": str(edge.get("tail") or tail_id),
                        "hop": hop,
                        "seed_node_ids": list(provenance["seed_node_ids"]),
                        "subclaim_ids": list(provenance["subclaim_ids"]),
                        "origins": list(provenance["origins"]),
                        "link_statuses": list(provenance["link_statuses"]),
                    }
                    evidence[key] = record
                    per_node_counts[source_id] += 1
                else:
                    record["hop"] = min(record["hop"], hop)
                    record["seed_node_ids"] = _merge_list(
                        record["seed_node_ids"], provenance["seed_node_ids"]
                    )
                    record["subclaim_ids"] = _merge_list(
                        record["subclaim_ids"], provenance["subclaim_ids"]
                    )
                    record["origins"] = _merge_list(
                        record["origins"], provenance["origins"]
                    )
                    record["link_statuses"] = _merge_list(
                        record["link_statuses"], provenance["link_statuses"]
                    )

                other_id = tail_id if source_id == head_id else head_id
                if other_id not in visited_nodes:
                    next_value = next_frontier.setdefault(
                        other_id,
                        {
                            "seed_node_ids": [],
                            "subclaim_ids": [],
                            "origins": [],
                            "link_statuses": [],
                        },
                    )
                    next_value["seed_node_ids"] = _merge_list(
                        next_value["seed_node_ids"], provenance["seed_node_ids"]
                    )
                    next_value["subclaim_ids"] = _merge_list(
                        next_value["subclaim_ids"], provenance["subclaim_ids"]
                    )
                    next_value["origins"] = _merge_list(
                        next_value["origins"], provenance["origins"]
                    )
                    next_value["link_statuses"] = _merge_list(
                        next_value["link_statuses"], provenance["link_statuses"]
                    )

        visited_nodes.update(next_frontier)
        frontier = next_frontier

    all_records = sorted(
        evidence.values(),
        key=lambda item: (item["hop"], item["head_id"], item["relation"], item["tail_id"]),
    )
    limited = all_records[:max_evidence_per_question]
    return {
        "evidence": limited,
        "n_before_question_cap": len(all_records),
        "n_after_question_cap": len(limited),
        "truncated": truncated_by_node or len(limited) < len(all_records),
        "truncated_count": max(0, len(all_records) - len(limited)),
    }
