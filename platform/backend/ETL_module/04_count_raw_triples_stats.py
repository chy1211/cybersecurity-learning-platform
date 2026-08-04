import argparse
import json
import os
from collections import Counter

MISSING = "__MISSING__"


def iter_json_files(root_dir):
    for root, _, files in os.walk(root_dir):
        for filename in files:
            if filename.lower().endswith(".json"):
                yield os.path.join(root, filename)


def safe_get_type(node):
    if isinstance(node, dict):
        return node.get("type") or MISSING
    return MISSING


def safe_get_name(node):
    if isinstance(node, dict):
        return node.get("name") or MISSING
    return MISSING


def load_triples(root_dir, include_names):
    entity_type_counts = Counter()
    entity_name_counts = Counter()
    relation_counts = Counter()
    edge_counts = Counter()

    files_processed = 0
    files_skipped = 0
    total_triples = 0
    errors = 0

    for path in iter_json_files(root_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                files_skipped += 1
                continue
            files_processed += 1
            for item in data:
                if not isinstance(item, dict):
                    continue
                s_node = item.get("subject", {})
                o_node = item.get("object", {})
                s_type = safe_get_type(s_node)
                o_type = safe_get_type(o_node)
                rel = item.get("relation") or MISSING

                entity_type_counts[s_type] += 1
                entity_type_counts[o_type] += 1
                relation_counts[rel] += 1
                edge_counts[(s_type, rel, o_type)] += 1

                if include_names:
                    s_name = safe_get_name(s_node)
                    o_name = safe_get_name(o_node)
                    entity_name_counts[(s_type, s_name)] += 1
                    entity_name_counts[(o_type, o_name)] += 1

                total_triples += 1
        except Exception as exc:
            errors += 1
            print(f"[WARN] Failed to read {path}: {exc}")

    return {
        "entity_type_counts": entity_type_counts,
        "entity_name_counts": entity_name_counts,
        "relation_counts": relation_counts,
        "edge_counts": edge_counts,
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "total_triples": total_triples,
        "errors": errors,
    }


def print_counter(title, counter, top):
    print("")
    print(title)
    if not counter:
        print("  (none)")
        return
    items = sorted(counter.items(), key=lambda x: (-x[1], str(x[0])))
    if top and top > 0:
        items = items[:top]
    for key, count in items:
        print(f"  {key}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Count entities, relations, and schema edges in RawTriples."
    )
    parser.add_argument(
        "--root",
        default="RawTriples",
        help="Root folder containing RawTriples JSON files.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Show only top N counts (0 means all).",
    )
    parser.add_argument(
        "--by-name",
        action="store_true",
        help="Also count entity names by type.",
    )
    args = parser.parse_args()

    root_dir = os.path.abspath(args.root)
    if not os.path.isdir(root_dir):
        print(f"[ERROR] Root folder not found: {root_dir}")
        return 1

    stats = load_triples(root_dir, args.by_name)
    print(f"Root: {root_dir}")
    print(f"Files processed: {stats['files_processed']}")
    print(f"Files skipped (non-list JSON): {stats['files_skipped']}")
    print(f"Errors: {stats['errors']}")
    print(f"Total triples: {stats['total_triples']}")
    print(f"Unique entity types: {len(stats['entity_type_counts'])}")
    print(f"Unique relations: {len(stats['relation_counts'])}")
    print(f"Unique schema edges: {len(stats['edge_counts'])}")

    print_counter("Entities by type", stats["entity_type_counts"], args.top)
    print_counter("Relations", stats["relation_counts"], args.top)

    edge_display = Counter()
    for (s_type, rel, o_type), count in stats["edge_counts"].items():
        edge_display[f"{s_type} | {rel} | {o_type}"] = count
    print_counter(
        "Schema edges (subject_type | relation | object_type)",
        edge_display,
        args.top,
    )

    if args.by_name:
        print_counter("Entities by name (type, name)", stats["entity_name_counts"], args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
