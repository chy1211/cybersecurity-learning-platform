#!/usr/bin/env python
"""Build an ETL rerun attribution report for oral-defense item #13."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[2]
WORKSPACE_DIR = SCRIPT_PATH.parents[6]
DEFAULT_MATCHGPT_CSV = BACKEND_DIR / "exp_1" / "MatchGPT" / "phase1_results" / "matchgpt_merged_t07.csv"
DEFAULT_AUDIT_LOG = BACKEND_DIR / "ETL_module" / "logs"
DEFAULT_OUT = WORKSPACE_DIR / "_tooling" / "rerun_test" / "attribution_report.md"
VALIDATION_STAGES = {"phase1_schema", "step1_class_property", "step2_uri", "step3_semantic"}
DISALLOWED_JSON_NAME_RE = re.compile(r"(^embedding_cache\.json$|_cache\.json$|embeddings|neo4j_backup_)", re.I)

CROSS_TYPE_COUNT_PATHS: Sequence[Tuple[Tuple[str, ...], str]] = (
    (("merge_stats", "cross_type_blocked"), "merge_stats.cross_type_blocked"),
    (("merge_stats", "cross_type_skip"), "merge_stats.cross_type_skip"),
    (("cross_type_blocked",), "cross_type_blocked"),
    (("cross_type_skip",), "cross_type_skip"),
)
CROSS_TYPE_RATE_PATHS: Sequence[Tuple[Tuple[str, ...], str]] = (
    (("merge_stats", "cross_type_merge_rate"), "merge_stats.cross_type_merge_rate"),
    (("merge_stats", "cross_type_block_rate"), "merge_stats.cross_type_block_rate"),
    (("cross_type_merge_rate",), "cross_type_merge_rate"),
    (("cross_type_block_rate",), "cross_type_block_rate"),
)
CROSS_TYPE_EXAMPLE_PATHS: Sequence[Tuple[str, ...]] = (
    ("merge_stats", "cross_type_examples"),
    ("merge_stats", "cross_type_blocked_examples"),
    ("merge_stats", "cross_type_pairs"),
    ("cross_type_examples",),
    ("cross_type_blocked_examples",),
    ("cross_type_pairs",),
)


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_DIR.resolve()))
    except Exception:
        return str(path)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "cp950"):
        try:
            text = path.read_text(encoding=encoding)
            return list(csv.DictReader(text.splitlines()))
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Cannot read CSV: {path} ({last_error})")


def iter_json_files(path: Path) -> Iterable[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return sorted(
        item
        for item in path.rglob("*.json")
        if item.is_file() and not DISALLOWED_JSON_NAME_RE.search(item.name)
    )


def load_json_list(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def load_json_object(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("stats JSON root must be an object")
    return data


def nested_value(data: Dict[str, Any], keys: Sequence[str]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def first_nested_value(data: Dict[str, Any], paths: Sequence[Tuple[Tuple[str, ...], str]]) -> Tuple[Any, str]:
    for keys, label in paths:
        value = nested_value(data, keys)
        if value is not None:
            return value, label
    return None, ""


def coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    return None


def coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def latest_audit_file(path: Path) -> Optional[Path]:
    if path.is_file():
        return path
    if not path.exists():
        return None
    files = sorted(path.glob("validation_audit_*.jsonl"), key=lambda item: item.stat().st_mtime)
    return files[-1] if files else None


def load_audit_records(path: Optional[Path]) -> Tuple[List[Dict[str, Any]], List[str], Optional[Path]]:
    if path is None:
        return [], ["audit log path was not provided."], None
    audit_file = latest_audit_file(path)
    if audit_file is None:
        return [], [f"audit log not found: {path}"], None

    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for line_no, line in enumerate(audit_file.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception as exc:
            warnings.append(f"{rel_path(audit_file)}:{line_no}: {type(exc).__name__}: {exc}")
            continue
        if isinstance(item, dict):
            records.append(item)
    return records, warnings, audit_file


def triple_text(triple: Dict[str, Any]) -> str:
    subject = triple.get("subject") or {}
    obj = triple.get("object") or {}
    return (
        f"({subject.get('name', '')} [{subject.get('type', '')}]) "
        f"-{triple.get('relation', '')}-> "
        f"({obj.get('name', '')} [{obj.get('type', '')}])"
    )


def example_from_audit(record: Dict[str, Any]) -> str:
    raw = record.get("raw_triple") if isinstance(record.get("raw_triple"), dict) else {}
    reason = record.get("reason_summary") or record.get("reason") or ""
    return f"{triple_text(raw)} | reason: {reason}"


def summarize_audit(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    accepted = []
    validation_rejected = []
    other = []
    stages = Counter()

    for record in records:
        decision = str(record.get("decision") or "").lower()
        stage = str(record.get("stage") or "")
        stages[stage] += 1
        if decision == "accept":
            accepted.append(record)
        elif decision == "reject" and stage in VALIDATION_STAGES:
            validation_rejected.append(record)
        elif decision == "reject":
            other.append(record)

    return {
        "candidate_count": len(records),
        "accepted_count": len(accepted),
        "validation_rejected_count": len(validation_rejected),
        "other_count": len(other),
        "validation_examples": [example_from_audit(item) for item in validation_rejected[:3]],
        "other_examples": [example_from_audit(item) for item in other[:3]],
        "stage_counts": stages,
    }


def load_legacy_dir_records(path: Optional[Path]) -> Tuple[int, List[Dict[str, Any]], List[str]]:
    if path is None:
        return 0, [], []
    count = 0
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if not path.exists():
        return 0, [], [f"path not found: {path}"]
    for json_file in iter_json_files(path):
        try:
            items = load_json_list(json_file)
        except Exception as exc:
            warnings.append(f"{rel_path(json_file)}: {type(exc).__name__}: {exc}")
            continue
        count += len(items)
        if len(records) < 3:
            records.extend(items[: 3 - len(records)])
    return count, records, warnings


def classify_reject_stage_from_reason(reason: str) -> str:
    if "Phase 1" in reason:
        return "phase1_schema"
    if "Step 1" in reason or "Class/Property" in reason:
        return "step1_class_property"
    if "Step 2" in reason or "URI" in reason:
        return "step2_uri"
    if "Step 3" in reason or "Semantic" in reason:
        return "step3_semantic"
    return "other"


def synthesize_audit_from_legacy_dirs(args: argparse.Namespace) -> Tuple[Dict[str, Any], List[str]]:
    raw_count, _, raw_warnings = load_legacy_dir_records(args.raw_dir)
    validated_count, _, validated_warnings = load_legacy_dir_records(args.validated_dir)
    rejected_count, rejected_examples_raw, rejected_warnings = load_legacy_dir_records(args.rejected_dir)

    examples = []
    other_examples = []
    validation_rejected_count = 0
    other_count = 0
    stage_counts = Counter()
    for item in rejected_examples_raw:
        reason = str(item.get("reject_reason") or "")
        stage = classify_reject_stage_from_reason(reason)
        stage_counts[stage] += 1
        source = item.get("original_raw_triple") if isinstance(item.get("original_raw_triple"), dict) else item
        rendered = f"{triple_text(source)} | reason: {reason}"
        if stage in VALIDATION_STAGES:
            validation_rejected_count += 1
            examples.append(rendered)
        else:
            other_count += 1
            other_examples.append(rendered)

    if rejected_count > len(rejected_examples_raw):
        validation_rejected_count = rejected_count - other_count

    candidate_count = raw_count if raw_count else validated_count + rejected_count
    warnings = (
        raw_warnings
        + validated_warnings
        + rejected_warnings
        + ["No audit jsonl was available; legacy counts were reconstructed from RawTriples/Validated/Rejected."]
    )
    return {
        "candidate_count": candidate_count,
        "accepted_count": validated_count,
        "validation_rejected_count": validation_rejected_count,
        "other_count": other_count,
        "validation_examples": examples[:3],
        "other_examples": other_examples[:3],
        "stage_counts": stage_counts,
    }, warnings


def find_column(columns: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    lower_to_actual = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lower_to_actual:
            return lower_to_actual[candidate.lower()]
    return None


def summarize_matchgpt(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    columns = list(rows[0].keys()) if rows else []
    status_col = find_column(
        columns,
        ["status", "outcome", "decision", "result", "merge_status", "merge_result", "action"],
    )
    cross_rows: List[Dict[str, str]] = []
    merged_rows: List[Dict[str, str]] = []
    data_gap = status_col is None

    for row in rows:
        type_a = str(row.get("type_a") or "").strip()
        type_b = str(row.get("type_b") or "").strip()
        if status_col:
            status = str(row.get(status_col) or "").lower()
            if "cross" in status and ("skip" in status or "block" in status or "type" in status):
                cross_rows.append(row)
                continue
            if "merge" in status or "merged" in status:
                merged_rows.append(row)
                continue
        elif not type_a or not type_b or type_a == type_b:
            merged_rows.append(row)

    return {
        "synonym_merged_count": len(merged_rows),
        "cross_type_blocked_count": len(cross_rows),
        "cross_type_merge_rate": None,
        "cross_type_data_gap": data_gap,
        "synonym_examples": [example_from_matchgpt(row) for row in merged_rows[:3]],
        "cross_type_examples": [example_from_matchgpt(row) for row in cross_rows[:3]],
        "cross_type_examples_from_stats": False,
        "cross_type_source": "MatchGPT status column",
        "cross_type_source_field": status_col or "",
        "cross_type_semantics": "blocked_candidate_pairs" if status_col else "unknown_without_stats",
        "columns": columns,
        "status_column": status_col or "",
    }


def example_from_matchgpt(row: Dict[str, str]) -> str:
    pair = (
        f"({row.get('name_a', '')} [{row.get('type_a', '')}]) <-> "
        f"({row.get('name_b', '')} [{row.get('type_b', '')}])"
    )
    reason = row.get("reason") or row.get("status") or row.get("outcome") or row.get("decision") or ""
    confidence = row.get("confidence") or ""
    suffix = f" | confidence: {confidence}" if confidence else ""
    return f"{pair} | reason: {reason}{suffix}"


def normalize_matchgpt_stat_examples(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    examples: List[str] = []
    for item in value[:3]:
        if isinstance(item, str):
            examples.append(item)
        elif isinstance(item, dict):
            if {"name_a", "name_b"} & set(item):
                row = {str(key): "" if val is None else str(val) for key, val in item.items()}
                examples.append(example_from_matchgpt(row))
            else:
                examples.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
    return examples


def read_matchgpt_stats(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    data = load_json_object(path)
    warnings: List[str] = []

    raw_count, count_field = first_nested_value(data, CROSS_TYPE_COUNT_PATHS)
    count = coerce_int(raw_count)
    if raw_count is not None and count is None:
        warnings.append(f"{rel_path(path)}: {count_field} is not an integer-compatible value.")

    raw_rate, rate_field = first_nested_value(data, CROSS_TYPE_RATE_PATHS)
    rate = coerce_float(raw_rate)
    if raw_rate is not None and rate is None:
        warnings.append(f"{rel_path(path)}: {rate_field} is not a numeric value.")

    examples: List[str] = []
    for keys in CROSS_TYPE_EXAMPLE_PATHS:
        examples = normalize_matchgpt_stat_examples(nested_value(data, keys))
        if examples:
            break

    return {
        "count": count,
        "count_field": count_field,
        "rate": rate,
        "rate_field": rate_field,
        "examples": examples,
    }, warnings


def apply_matchgpt_stats(matchgpt: Dict[str, Any], stats_path: Path) -> List[str]:
    stats, warnings = read_matchgpt_stats(stats_path)
    if stats["count"] is None:
        warnings.append(
            f"{rel_path(stats_path)}: no supported cross-type count field found "
            f"({', '.join(label for _, label in CROSS_TYPE_COUNT_PATHS)})."
        )
        return warnings

    matchgpt["cross_type_blocked_count"] = stats["count"]
    matchgpt["cross_type_merge_rate"] = stats["rate"]
    matchgpt["cross_type_data_gap"] = False
    matchgpt["cross_type_source"] = "MatchGPT stats JSON"
    matchgpt["cross_type_source_field"] = stats["count_field"]
    matchgpt["cross_type_semantics"] = "blocked_candidate_pairs"
    if stats["examples"]:
        matchgpt["cross_type_examples"] = stats["examples"]
        matchgpt["cross_type_examples_from_stats"] = True
    return warnings


def append_examples(lines: List[str], examples: Sequence[str], empty_note: str) -> None:
    if not examples:
        lines.append(f"  - {empty_note}")
        return
    for item in examples:
        lines.append(f"  - {item}")


def write_report(
    out_path: Path,
    args: argparse.Namespace,
    audit_source: Optional[Path],
    audit: Dict[str, Any],
    matchgpt: Dict[str, Any],
    warnings: Sequence[str],
) -> None:
    lines: List[str] = []
    lines.append("# ETL rerun attribution report for oral-defense item 13")
    lines.append("")
    lines.append(f"generated_at: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"audit_source: {rel_path(audit_source) if audit_source else 'legacy_dirs'}")
    lines.append(f"matchgpt_source: {rel_path(args.matchgpt_csv)}")
    if args.matchgpt_stats:
        lines.append(f"matchgpt_stats_source: {rel_path(args.matchgpt_stats)}")
    lines.append("")
    lines.append("## Machine Summary")
    lines.append(f"candidate_triples_count: {audit['candidate_count']}")
    lines.append(f"accepted_triples_count: {audit['accepted_count']}")
    lines.append(f"validation_rejected_count: {audit['validation_rejected_count']}")
    lines.append(f"synonym_merged_count: {matchgpt['synonym_merged_count']}")
    lines.append(f"cross_type_blocked_count: {matchgpt['cross_type_blocked_count']}")
    if matchgpt["cross_type_merge_rate"] is not None:
        lines.append(f"cross_type_merge_rate: {matchgpt['cross_type_merge_rate']}")
    lines.append(f"cross_type_semantics: {matchgpt['cross_type_semantics']}")
    lines.append(f"other_count: {audit['other_count']}")
    lines.append(f"cross_type_data_gap: {str(matchgpt['cross_type_data_gap']).lower()}")
    lines.append("")
    lines.append("## Attribution Table")
    lines.append("| category | unit | count | source |")
    lines.append("|---|---:|---:|---|")
    lines.append(f"| 驗證拒絕 | triple | {audit['validation_rejected_count']} | validation audit / Rejected |")
    lines.append(f"| 同義整併 | pair | {matchgpt['synonym_merged_count']} | MatchGPT merge CSV |")
    cross_source = matchgpt["cross_type_source"]
    if matchgpt["cross_type_source_field"]:
        cross_source = f"{cross_source}: {matchgpt['cross_type_source_field']}"
    lines.append(f"| 跨類阻擋 | pair | {matchgpt['cross_type_blocked_count']} | {cross_source} |")
    lines.append(f"| 其他 | triple | {audit['other_count']} | audit reject records outside validation stages |")
    lines.append("")
    lines.append("## Examples")
    lines.append("### 驗證拒絕")
    append_examples(lines, audit["validation_examples"], "0 examples in source data")
    lines.append("")
    lines.append("### 同義整併")
    append_examples(lines, matchgpt["synonym_examples"], "0 examples in source data")
    lines.append("")
    lines.append("### 跨類阻擋")
    if matchgpt["cross_type_data_gap"]:
        lines.append("  - Data gap: MatchGPT CSV has no explicit cross-type status/decision column.")
    elif args.matchgpt_stats and not matchgpt["cross_type_examples"]:
        lines.append("  - MatchGPT stats JSON provides aggregate cross-type count only; no examples were present.")
    append_examples(lines, matchgpt["cross_type_examples"], "0 examples in source data")
    lines.append("")
    lines.append("### 其他")
    append_examples(lines, audit["other_examples"], "0 examples in source data")
    lines.append("")
    if warnings:
        lines.append("## Notes")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ETL validation/MatchGPT attribution report.")
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT_LOG, help="Audit jsonl file or logs folder.")
    parser.add_argument("--matchgpt-csv", type=Path, default=DEFAULT_MATCHGPT_CSV, help="MatchGPT merge/status CSV.")
    parser.add_argument("--matchgpt-stats", type=Path, help="Optional MatchGPT metrics JSON with cross-type stats.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="UTF-8 Markdown report path.")
    parser.add_argument("--raw-dir", type=Path, default=BACKEND_DIR / "ETL_module" / "RawTriples")
    parser.add_argument("--validated-dir", type=Path, default=BACKEND_DIR / "ETL_module" / "Validated")
    parser.add_argument("--rejected-dir", type=Path, default=BACKEND_DIR / "ETL_module" / "Rejected")
    parser.add_argument(
        "--legacy-dirs-if-missing-audit",
        action="store_true",
        help="Use RawTriples/Validated/Rejected counts when audit jsonl is missing.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    audit_records, warnings, audit_source = load_audit_records(args.audit_log)
    if audit_records:
        audit_summary = summarize_audit(audit_records)
    elif args.legacy_dirs_if_missing_audit:
        audit_summary, legacy_warnings = synthesize_audit_from_legacy_dirs(args)
        warnings.extend(legacy_warnings)
    else:
        raise SystemExit("Audit log is required unless --legacy-dirs-if-missing-audit is set.")

    matchgpt_rows = read_csv_rows(args.matchgpt_csv)
    matchgpt_summary = summarize_matchgpt(matchgpt_rows)
    if args.matchgpt_stats:
        warnings.extend(apply_matchgpt_stats(matchgpt_summary, args.matchgpt_stats))
    if matchgpt_summary["cross_type_data_gap"]:
        warnings.append("MatchGPT CSV has no explicit cross-type status/decision column.")

    write_report(args.out, args, audit_source, audit_summary, matchgpt_summary, warnings)
    print(
        "OK attribution_report "
        f"candidates={audit_summary['candidate_count']} "
        f"accepted={audit_summary['accepted_count']} "
        f"validation_rejected={audit_summary['validation_rejected_count']} "
        f"synonym_merged={matchgpt_summary['synonym_merged_count']} "
        f"cross_type_blocked={matchgpt_summary['cross_type_blocked_count']} "
        f"cross_type_merge_rate={matchgpt_summary['cross_type_merge_rate']} "
        f"other={audit_summary['other_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
