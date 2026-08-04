"""Fixed, auditable evidence ordering and prompt budget for B4 Step 4."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


STATUS_RANK = {"exact": 0, "alias": 1, "semantic": 2}


def deduplicate_evidence(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        key = (
            str(record.get("head_id") or record.get("head") or ""),
            str(record.get("relation") or ""),
            str(record.get("tail_id") or record.get("tail") or ""),
        )
        if not all(key):
            raise ValueError(f"evidence triple has incomplete identity: {record}")
        if key not in merged:
            record["head_id"], record["relation"], record["tail_id"] = key
            for field in ("seed_node_ids", "subclaim_ids", "origins", "link_statuses"):
                record[field] = sorted(set(record.get(field, [])), key=str)
            merged[key] = record
            continue
        current = merged[key]
        current["hop"] = min(int(current.get("hop", 99)), int(record.get("hop", 99)))
        for field in ("seed_node_ids", "subclaim_ids", "origins", "link_statuses"):
            current[field] = sorted(
                set(current.get(field, [])).union(record.get(field, [])), key=str
            )
        if record.get("conflict_group"):
            current["conflict_group"] = record["conflict_group"]
    return list(merged.values())


def _sort_key(record: dict[str, Any]) -> tuple:
    statuses = record.get("link_statuses", []) or ["semantic"]
    best_status = min(STATUS_RANK.get(status, 99) for status in statuses)
    return (
        int(record.get("hop", 99)),
        best_status,
        -len(record.get("subclaim_ids", [])),
        -len(record.get("origins", [])),
        str(record.get("head_id", "")),
        str(record.get("relation", "")),
        str(record.get("tail_id", "")),
    )


def rank_and_budget_evidence(
    records: Iterable[dict[str, Any]],
    *,
    max_per_origin: int = 10,
    max_total: int = 30,
) -> dict[str, Any]:
    """Rank evidence lexicographically and enforce source + total caps."""

    if max_per_origin < 1 or max_total < 1:
        raise ValueError("evidence caps must be positive")
    unique = sorted(deduplicate_evidence(records), key=_sort_key)
    origin_counts: defaultdict[str, int] = defaultdict(int)
    kept: list[dict[str, Any]] = []
    skipped_for_origin = 0
    for record in unique:
        origins = sorted(set(record.get("origins", []))) or ["unknown"]
        if all(origin_counts[origin] >= max_per_origin for origin in origins):
            skipped_for_origin += 1
            continue
        kept.append(record)
        for origin in origins:
            origin_counts[origin] += 1
        if len(kept) >= max_total:
            break
    for rank, record in enumerate(kept, start=1):
        record["rank"] = rank
    return {
        "evidence": kept,
        "n_input_unique": len(unique),
        "n_kept": len(kept),
        "truncated": len(kept) < len(unique),
        "truncated_count": max(0, len(unique) - len(kept)),
        "skipped_for_origin_cap": skipped_for_origin,
        "origin_counts": dict(sorted(origin_counts.items())),
    }


def prompt_triples(records: Iterable[dict[str, Any]]) -> list[list[str]]:
    """Expose only plain triples to the answering model."""

    return [
        [str(record["head"]), str(record["relation"]), str(record["tail"])]
        for record in records
    ]
