#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RQ1 ontology usage statistics for thesis Chapter 4.

The script is intentionally parameterized so a rebuilt KG can be evaluated by
pointing the arguments at a new ETL output folder or Neo4j instance.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


EXPECTED_SCHEMA_EDGES = 98
EXPECTED_CANDIDATES = 5593
EXPECTED_VALIDATED = 5486
EXPECTED_REJECTED = 107
EXPECTED_SEMANTIC_REJECTED = 95
EXPECTED_STRUCTURE_REJECTED = 11
EXPECTED_CLASS_ALIGNMENT_REJECTED = 1

SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[1]
PROJECT_DIR = SCRIPT_PATH.parents[2]
WORKSPACE_DIR = SCRIPT_PATH.parents[5] if len(SCRIPT_PATH.parents) > 5 else Path.cwd()
ONTOLOGY_DIR = WORKSPACE_DIR / "論文" / "本體論"

DEFAULT_SCHEMA_CSV = ONTOLOGY_DIR / "schema_edges.csv"
DEFAULT_RELATIONS_CSV = ONTOLOGY_DIR / "relations.csv"
DEFAULT_CANDIDATES = BACKEND_DIR / "ETL_module" / "RawTriples"
DEFAULT_VALIDATED = BACKEND_DIR / "ETL_module" / "Validated"
DEFAULT_REJECTED = BACKEND_DIR / "ETL_module" / "Rejected"
DEFAULT_OUT = WORKSPACE_DIR / "_tooling" / "rq1_ontology_usage_report.txt"

NEW_ENTITY_TYPES = ["principle", "risk", "policy"]
DISALLOWED_JSON_NAME_RE = re.compile(r"(^embedding_cache\.json$|_cache\.json$|embeddings)", re.I)


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "cp950"):
        try:
            text = path.read_text(encoding=encoding)
            return list(csv.DictReader(text.splitlines()))
        except Exception as exc:  # pragma: no cover - kept for mixed local encodings
            last_error = exc
    raise RuntimeError(f"Cannot read CSV: {path} ({last_error})")


def unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for value in values:
        cleaned = value.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen.keys())


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_DIR.resolve()))
    except Exception:
        return str(path)


def list_json_files(path: Path) -> Tuple[List[Path], List[str]]:
    warnings: List[str] = []
    if not path.exists():
        return [], [f"路徑不存在：{path}"]
    if path.is_file():
        files = [path]
    else:
        files = sorted(p for p in path.rglob("*.json") if p.is_file())

    safe_files: List[Path] = []
    for file_path in files:
        if DISALLOWED_JSON_NAME_RE.search(file_path.name):
            warnings.append(f"略過禁止讀取的大型/快取 JSON：{rel_path(file_path)}")
            continue
        safe_files.append(file_path)
    return safe_files, warnings


def load_json_list(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("JSON root is not a list")
    return [item for item in data if isinstance(item, dict)]


def triple_tuple(triple: Dict[str, Any], use_original: bool = False) -> Tuple[str, str, str]:
    source = triple
    if use_original and isinstance(triple.get("original_raw_triple"), dict):
        source = triple["original_raw_triple"]
    subject = source.get("subject") or {}
    obj = source.get("object") or {}
    return (
        normalize(subject.get("type")),
        normalize(source.get("relation")),
        normalize(obj.get("type")),
    )


def load_schema_edges(path: Path) -> Dict[str, Any]:
    rows = read_csv_rows(path)
    legal_edges = [
        (
            normalize(row.get("主體 (Subject)")),
            normalize(row.get("關係 (Relation)")),
            normalize(row.get("受體 (Object)")),
        )
        for row in rows
    ]
    legal_set = set(legal_edges)
    warnings: List[str] = []
    if len(rows) != EXPECTED_SCHEMA_EDGES:
        warnings.append(f"Schema Edges row count is {len(rows)}, expected {EXPECTED_SCHEMA_EDGES}.")
    if len(legal_set) != len(legal_edges):
        warnings.append(f"Schema Edges has {len(legal_edges) - len(legal_set)} duplicate tuple rows.")
    return {"rows": rows, "legal_edges": legal_edges, "legal_set": legal_set, "warnings": warnings}


def load_added_relations(path: Path) -> Dict[str, Any]:
    rows = read_csv_rows(path)
    added = [
        row.get("關係 (Relation)", "").strip()
        for row in rows
        if "新增" in (row.get("來源") or "")
    ]
    relations = unique_preserve_order(added)
    warnings: List[str] = []
    if len(rows) != 16:
        warnings.append(f"Relations row count is {len(rows)}, expected 16.")
    if len(relations) != 7:
        warnings.append(f"Added relation type count is {len(relations)}, expected 7.")
    return {"rows": rows, "relations": relations, "warnings": warnings}


def count_boundary_usage(path: Path, legal_edges: set[Tuple[str, str, str]], use_original: bool) -> Dict[str, Any]:
    files, warnings = list_json_files(path)
    total = 0
    inside = 0
    outside = Counter()
    file_errors: List[str] = []

    for file_path in files:
        try:
            triples = load_json_list(file_path)
        except Exception as exc:
            file_errors.append(f"{rel_path(file_path)}: {type(exc).__name__}: {exc}")
            continue
        for triple in triples:
            key = triple_tuple(triple, use_original=use_original)
            total += 1
            if key in legal_edges:
                inside += 1
            else:
                outside[key] += 1

    return {
        "path": path,
        "file_count": len(files),
        "total": total,
        "inside": inside,
        "outside": total - inside,
        "outside_top10": outside.most_common(10),
        "warnings": warnings,
        "file_errors": file_errors,
    }


def count_triples(path: Path, use_original: bool = False) -> Dict[str, Any]:
    files, warnings = list_json_files(path)
    total = 0
    errors: List[str] = []
    for file_path in files:
        try:
            total += len(load_json_list(file_path))
        except Exception as exc:
            errors.append(f"{rel_path(file_path)}: {type(exc).__name__}: {exc}")
    return {"path": path, "file_count": len(files), "total": total, "warnings": warnings, "file_errors": errors}


def classify_rejection(reject_reason: str) -> str:
    reason = reject_reason or ""
    if "Step 3" in reason or "Semantic Violation" in reason:
        return "語意違規"
    if "Phase 1" in reason or "Schema Edge Violation" in reason:
        return "關係結構違規"
    if "Step 1" in reason or "Class/Property" in reason:
        return "類別對齊違規"
    return "未分類"


def count_rejections(path: Path) -> Dict[str, Any]:
    files, warnings = list_json_files(path)
    total = 0
    stages = Counter()
    reason_heads = Counter()
    errors: List[str] = []
    examples: Dict[str, str] = {}

    for file_path in files:
        try:
            triples = load_json_list(file_path)
        except Exception as exc:
            errors.append(f"{rel_path(file_path)}: {type(exc).__name__}: {exc}")
            continue
        for triple in triples:
            total += 1
            reason = str(triple.get("reject_reason") or "")
            stage = classify_rejection(reason)
            stages[stage] += 1
            head = reason.split(":", 1)[0] if reason else "MISSING"
            reason_heads[head] += 1
            examples.setdefault(head, reason[:200])

    return {
        "path": path,
        "file_count": len(files),
        "total": total,
        "stages": stages,
        "reason_heads": reason_heads,
        "examples": examples,
        "warnings": warnings,
        "file_errors": errors,
    }


def cypher_identifier(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def neo4j_stats(
    uri: str,
    user: str,
    password: str,
    database: Optional[str],
    new_entities: Sequence[str],
    added_relations: Sequence[str],
) -> Dict[str, Any]:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5)
    try:
        driver.verify_connectivity()
        session_kwargs = {"database": database} if database else {}
        with driver.session(**session_kwargs) as session:
            node_total = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rel_total = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            # 2026-07-11 修正：MatchGPT 整併後為 :Entity/RELATION 泛型 schema（語意
            # 存於 n.type / r.relation 屬性），label/關係型別查詢必然回 0。偵測到
            # 泛型 schema 時改用屬性層計數；03-schema 圖維持原 label 計數。
            entity_labeled = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
            generic_schema = node_total > 0 and entity_labeled == node_total
            entity_counts = OrderedDict()
            relation_counts = OrderedDict()
            if generic_schema:
                for label in new_entities:
                    entity_counts[label] = session.run(
                        "MATCH (n:Entity) WHERE toLower(coalesce(n.type, '')) = toLower($t) "
                        "RETURN count(n) AS c", t=label).single()["c"]
                for rel_type in added_relations:
                    relation_counts[rel_type] = session.run(
                        "MATCH ()-[r:RELATION]->() WHERE toLower(coalesce(r.relation, '')) = toLower($t) "
                        "RETURN count(r) AS c", t=rel_type).single()["c"]
            else:
                for label in new_entities:
                    query = f"MATCH (n:{cypher_identifier(label)}) RETURN count(n) AS c"
                    entity_counts[label] = session.run(query).single()["c"]
                for rel_type in added_relations:
                    query = f"MATCH ()-[r:{cypher_identifier(rel_type)}]->() RETURN count(r) AS c"
                    relation_counts[rel_type] = session.run(query).single()["c"]
        return {
            "available": True,
            "source": "neo4j",
            "source_detail": uri if not database else f"{uri} database={database}",
            "count_mode": ("property-based (generic :Entity/RELATION schema)"
                           if generic_schema else "label-based (per-class schema)"),
            "node_total": int(node_total),
            "rel_total": int(rel_total),
            "entity_counts": entity_counts,
            "relation_counts": relation_counts,
            "warnings": [],
        }
    finally:
        driver.close()


def find_latest_backup(root: Path) -> Optional[Path]:
    backups = [p for p in root.rglob("neo4j_backup_*.json") if p.is_file()]
    if not backups:
        return None
    return max(backups, key=lambda p: p.stat().st_mtime)


def iter_named_array_objects(path: Path, key: str) -> Iterator[Dict[str, Any]]:
    token = f'"{key}"'
    window = ""
    found_key = False
    in_array = False
    started = False
    depth = 0
    in_string = False
    escape = False
    buffer: List[str] = []

    with path.open("r", encoding="utf-8-sig") as handle:
        while True:
            char = handle.read(1)
            if not char:
                break

            if not found_key:
                window = (window + char)[-len(token) :]
                if window == token:
                    found_key = True
                continue

            if not in_array:
                if char == "[":
                    in_array = True
                continue

            if not started:
                if char == "{":
                    started = True
                    depth = 1
                    in_string = False
                    escape = False
                    buffer = ["{"]
                elif char == "]":
                    break
                continue

            buffer.append(char)
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        yield json.loads("".join(buffer))
                        started = False
                        buffer = []


def backup_stats(path: Path, new_entities: Sequence[str], added_relations: Sequence[str]) -> Dict[str, Any]:
    if DISALLOWED_JSON_NAME_RE.search(path.name):
        raise RuntimeError(f"Refusing to read disallowed JSON backup path: {path}")
    new_entity_set = {normalize(label) for label in new_entities}
    added_rel_set = {normalize(rel) for rel in added_relations}
    entity_counts = OrderedDict((label, 0) for label in new_entities)
    relation_counts = OrderedDict((rel, 0) for rel in added_relations)
    node_total = 0
    rel_total = 0

    for node in iter_named_array_objects(path, "nodes"):
        node_total += 1
        labels = {normalize(label) for label in node.get("labels", [])}
        for label in new_entity_set.intersection(labels):
            entity_counts[label] += 1

    for relationship in iter_named_array_objects(path, "relationships"):
        rel_total += 1
        rel_type = normalize(relationship.get("rel_type") or relationship.get("type"))
        if rel_type in added_rel_set:
            relation_counts[rel_type] += 1

    return {
        "available": True,
        "source": "backup_json_stream",
        "source_detail": str(path),
        "node_total": node_total,
        "rel_total": rel_total,
        "entity_counts": entity_counts,
        "relation_counts": relation_counts,
        "warnings": ["Neo4j connection failed; counts were computed by streaming neo4j_backup_*.json."],
    }


def get_graph_stats(args: argparse.Namespace, added_relations: Sequence[str]) -> Dict[str, Any]:
    errors: List[str] = []
    if args.neo4j_uri:
        try:
            return neo4j_stats(args.neo4j_uri, args.user, args.password, args.database, NEW_ENTITY_TYPES, added_relations)
        except Exception as exc:
            errors.append(f"Neo4j connection/query failed: {type(exc).__name__}: {str(exc).splitlines()[0]}")

    backup_path = args.backup
    if backup_path is None:
        backup_path = find_latest_backup(args.backend_dir)
    if backup_path is not None and backup_path.exists():
        try:
            stats = backup_stats(backup_path, NEW_ENTITY_TYPES, added_relations)
            stats["warnings"] = errors + stats.get("warnings", [])
            return stats
        except Exception as exc:
            errors.append(f"Backup stream failed: {type(exc).__name__}: {exc}")

    return {
        "available": False,
        "source": "unavailable",
        "source_detail": "",
        "node_total": 0,
        "rel_total": 0,
        "entity_counts": OrderedDict((label, 0) for label in NEW_ENTITY_TYPES),
        "relation_counts": OrderedDict((rel, 0) for rel in added_relations),
        "warnings": errors + [f"No neo4j_backup_*.json found under {args.backend_dir}."],
    }


def pct(part: int, total: int) -> float:
    return (part / total * 100.0) if total else 0.0


def match_text(actual: int, expected: int) -> str:
    status = "吻合" if actual == expected else "不吻合"
    return f"{status}（實測 {actual:,}；已知 {expected:,}）"


def write_report(
    out_path: Path,
    args: argparse.Namespace,
    schema: Dict[str, Any],
    relations: Dict[str, Any],
    boundary: Dict[str, Any],
    boundary_source_label: str,
    validated: Dict[str, Any],
    rejected: Dict[str, Any],
    graph: Dict[str, Any],
) -> None:
    lines: List[str] = []
    lines.append("RQ1 本體論使用率統計報告")
    lines.append(f"產生時間：{datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("一、輸入檔與資料來源")
    lines.append(f"- Schema Edges CSV：{rel_path(args.schema_csv)}")
    lines.append(f"- Relations CSV：{rel_path(args.relations_csv)}")
    lines.append(f"- 候選三元組來源：{boundary_source_label}；{rel_path(boundary['path'])}")
    lines.append(f"- 驗證通過三元組來源：{rel_path(args.validated)}")
    lines.append(f"- 拒絕清單來源：{rel_path(args.rejected)}")
    if graph["available"]:
        lines.append(f"- 最終圖譜來源：{graph['source']}；{graph['source_detail']}")
    else:
        lines.append("- 最終圖譜來源：不可用")
    lines.append("")

    all_warnings = (
        schema["warnings"]
        + relations["warnings"]
        + boundary["warnings"]
        + boundary["file_errors"]
        + validated["warnings"]
        + validated["file_errors"]
        + rejected["warnings"]
        + rejected["file_errors"]
        + graph.get("warnings", [])
    )
    if all_warnings:
        lines.append("資料口徑與警告")
        for warning in all_warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("二、合法邊界內生成率")
    lines.append(f"- Schema Edges row count：{len(schema['rows']):,}（預期 98）")
    lines.append(f"- Schema Edges unique tuple count：{len(schema['legal_set']):,}")
    lines.append(f"- 候選三元組檔案數：{boundary['file_count']:,}")
    lines.append(f"- 候選三元組總筆數：{boundary['total']:,}")
    lines.append(f"- 落在 98 合法邊界內筆數：{boundary['inside']:,}")
    lines.append(f"- 不在合法邊界內筆數：{boundary['outside']:,}")
    lines.append(f"- 合法邊界內生成率：{pct(boundary['inside'], boundary['total']):.2f}%")
    lines.append("- 不在合法邊界內之組合 Top-10：")
    if boundary["outside_top10"]:
        for (subject_type, relation, object_type), count in boundary["outside_top10"]:
            lines.append(f"  - {count:,}：({subject_type}, {relation}, {object_type})")
    else:
        lines.append("  - 無")
    lines.append("")

    lines.append("三、結構違規拒絕數")
    lines.append(f"- 拒絕清單檔案數：{rejected['file_count']:,}")
    lines.append(f"- 總拒絕筆數：{rejected['total']:,}")
    for label in ("語意違規", "關係結構違規", "類別對齊違規", "未分類"):
        if rejected["stages"].get(label, 0):
            lines.append(f"- {label}：{rejected['stages'][label]:,}")
    lines.append("- reject_reason 前綴統計：")
    for head, count in rejected["reason_heads"].most_common():
        lines.append(f"  - {count:,}：{head}")
    lines.append("")

    lines.append("四、新增實體與新增關係使用率")
    lines.append(f"- 新增實體類型：{', '.join(NEW_ENTITY_TYPES)}")
    lines.append(f"- 新增關係類型（Relations CSV 來源=(新增)）：{', '.join(relations['relations'])}")
    if graph["available"]:
        entity_total = sum(graph["entity_counts"].values())
        relation_total = sum(graph["relation_counts"].values())
        if graph.get("count_mode"):
            lines.append(f"- 計數模式：{graph['count_mode']}")
        lines.append(f"- 最終圖譜節點總數：{graph['node_total']:,}")
        lines.append(f"- 新增實體節點總數：{entity_total:,}（{pct(entity_total, graph['node_total']):.2f}%）")
        for label, count in graph["entity_counts"].items():
            lines.append(f"  - {label}：{count:,}（{pct(count, graph['node_total']):.2f}%）")
        lines.append(f"- 最終圖譜關係總數：{graph['rel_total']:,}")
        lines.append(f"- 新增關係邊總數：{relation_total:,}（{pct(relation_total, graph['rel_total']):.2f}%）")
        for rel_type, count in graph["relation_counts"].items():
            lines.append(f"  - {rel_type}：{count:,}（{pct(count, graph['rel_total']):.2f}%）")
    else:
        lines.append("- 最終圖譜統計不可用：Neo4j 連線失敗，且找不到可串流統計的 neo4j_backup_*.json。")
    lines.append("")

    structure_and_class = rejected["stages"].get("關係結構違規", 0) + rejected["stages"].get("類別對齊違規", 0)
    lines.append("五、與表9已知數對照")
    lines.append(f"- 候選三元組 5,593：{match_text(boundary['total'], EXPECTED_CANDIDATES)}")
    lines.append(f"- 通過驗證三元組 5,486：{match_text(validated['total'], EXPECTED_VALIDATED)}")
    lines.append(f"- 總拒絕 107：{match_text(rejected['total'], EXPECTED_REJECTED)}")
    lines.append(f"- 結構 11 + 類別 1 = 12：{match_text(structure_and_class, EXPECTED_STRUCTURE_REJECTED + EXPECTED_CLASS_ALIGNMENT_REJECTED)}")
    lines.append(f"  - 關係結構違規 11：{match_text(rejected['stages'].get('關係結構違規', 0), EXPECTED_STRUCTURE_REJECTED)}")
    lines.append(f"  - 類別對齊違規 1：{match_text(rejected['stages'].get('類別對齊違規', 0), EXPECTED_CLASS_ALIGNMENT_REJECTED)}")
    lines.append(f"  - 語意違規 95：{match_text(rejected['stages'].get('語意違規', 0), EXPECTED_SEMANTIC_REJECTED)}")
    lines.append("")
    lines.append("註：合法邊界內生成率只檢查候選三元組的 (主體類別, 關係, 受體類別) 是否落在 98 條 Schema Edges；")
    lines.append("其分母是 LLM 初始候選三元組，不等同於四階段驗證後的 5,486 筆有效三元組。")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    env_values = read_env_file(BACKEND_DIR / ".env")
    env_example_values = read_env_file(BACKEND_DIR / ".env.example")
    default_uri = os.getenv("NEO4J_URI") or env_values.get("NEO4J_URI") or env_example_values.get("NEO4J_URI") or "bolt://localhost:7687"
    default_user = os.getenv("NEO4J_USER") or env_values.get("NEO4J_USER") or env_example_values.get("NEO4J_USER") or "neo4j"
    default_password = os.getenv("NEO4J_PASSWORD") or env_values.get("NEO4J_PASSWORD") or env_example_values.get("NEO4J_PASSWORD") or "password"
    default_database = os.getenv("NEO4J_DATABASE") or env_values.get("NEO4J_DATABASE") or env_example_values.get("NEO4J_DATABASE") or None

    parser = argparse.ArgumentParser(description="Build RQ1 ontology usage statistics report.")
    parser.add_argument("--neo4j-uri", "--uri", dest="neo4j_uri", default=default_uri, help="Neo4j URI for final graph statistics.")
    parser.add_argument("--user", default=default_user, help="Neo4j username.")
    parser.add_argument("--password", default=default_password, help="Neo4j password. Prefer env vars for reruns.")
    parser.add_argument("--database", "--db", dest="database", default=default_database, help="Optional Neo4j database name.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES, help="Raw candidate triples file or folder.")
    parser.add_argument("--schema-csv", type=Path, default=DEFAULT_SCHEMA_CSV, help="Schema Edges CSV path.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="UTF-8 report output path.")
    parser.add_argument("--relations-csv", type=Path, default=DEFAULT_RELATIONS_CSV, help="Relations CSV path.")
    parser.add_argument("--validated", type=Path, default=DEFAULT_VALIDATED, help="Validated triples file or folder.")
    parser.add_argument("--rejected", type=Path, default=DEFAULT_REJECTED, help="Rejected triples file or folder.")
    parser.add_argument("--backup", type=Path, default=None, help="Optional neo4j_backup_*.json fallback path.")
    parser.add_argument("--backend-dir", type=Path, default=BACKEND_DIR, help="Backend dir used to auto-find neo4j_backup_*.json.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    schema = load_schema_edges(args.schema_csv)
    relations = load_added_relations(args.relations_csv)

    boundary = count_boundary_usage(args.candidates, schema["legal_set"], use_original=False)
    boundary_source_label = "RawTriples 原始候選三元組"
    if boundary["total"] == 0:
        validated_boundary = count_boundary_usage(args.validated, schema["legal_set"], use_original=True)
        rejected_boundary = count_boundary_usage(args.rejected, schema["legal_set"], use_original=True)
        combined_top = Counter()
        for key, count in validated_boundary["outside_top10"] + rejected_boundary["outside_top10"]:
            combined_top[key] += count
        boundary = {
            "path": Path(f"{args.validated} + {args.rejected}"),
            "file_count": validated_boundary["file_count"] + rejected_boundary["file_count"],
            "total": validated_boundary["total"] + rejected_boundary["total"],
            "inside": validated_boundary["inside"] + rejected_boundary["inside"],
            "outside": validated_boundary["outside"] + rejected_boundary["outside"],
            "outside_top10": combined_top.most_common(10),
            "warnings": validated_boundary["warnings"] + rejected_boundary["warnings"] + ["找不到候選三元組原始檔，改用 Validated + Rejected 以 original_raw_triple 重建近似值。"],
            "file_errors": validated_boundary["file_errors"] + rejected_boundary["file_errors"],
        }
        boundary_source_label = "Validated + Rejected 近似重建"

    validated = count_triples(args.validated)
    rejected = count_rejections(args.rejected)
    graph = get_graph_stats(args, relations["relations"])

    write_report(args.out, args, schema, relations, boundary, boundary_source_label, validated, rejected, graph)

    graph_status = "graph=unavailable"
    if graph["available"]:
        graph_status = f"graph={graph['source']} nodes={graph['node_total']} rels={graph['rel_total']}"
    print(
        "OK "
        f"report=_tooling/rq1_ontology_usage_report.txt "
        f"schema_rows={len(schema['rows'])} "
        f"candidates={boundary['total']} "
        f"inside={boundary['inside']} "
        f"rejected={rejected['total']} "
        f"{graph_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
