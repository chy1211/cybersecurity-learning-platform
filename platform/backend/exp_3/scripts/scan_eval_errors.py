#!/usr/bin/env python3
"""Scan exp_3 eval JSON files for API, parse, and empty-answer rows."""
from __future__ import annotations

import argparse
import glob
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOB = ROOT / "data" / "eval_results" / "eval_*_NF1.json"
ARMS = ("llm_only", "graph_rag")
KNOWN_MODELS = ("llama70b", "gemma31b", "gptoss", "llama8b", "gemma", "e4b", "phi")
MODEL_ORDER = ("e4b", "gptoss", "gemma31b", "llama70b", "phi", "gemma", "llama8b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan eval result JSON files for retry-worthy errors."
    )
    parser.add_argument(
        "--glob",
        default=str(DEFAULT_GLOB),
        help="Glob pattern for eval JSON files. Ignored when --files is used.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Explicit eval JSON files to scan.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="UTF-8 report path. When omitted, only ASCII stdout summary is printed.",
    )
    return parser.parse_args()


def resolve_files(args: argparse.Namespace) -> list[Path]:
    if args.files:
        files = [Path(item) for item in args.files]
    else:
        files = [Path(item) for item in glob.glob(args.glob)]
    files = [path.resolve() for path in files]
    if not files:
        raise SystemExit("NO_FILES=1")
    missing = [path for path in files if not path.exists()]
    if missing:
        raise SystemExit("MISSING_FILES=" + str(len(missing)))
    return sorted(files, key=lambda path: path.name)


def infer_model(path: Path) -> str:
    stem = path.stem
    if stem.startswith("eval_"):
        stem = stem[5:]
    for model in KNOWN_MODELS:
        if stem == model or stem.startswith(model + "_"):
            return model
    match = re.match(r"([A-Za-z0-9-]+)", stem)
    return match.group(1) if match else stem


def sort_key(key: tuple[str, str]) -> tuple[int, str, int]:
    model, arm = key
    model_rank = MODEL_ORDER.index(model) if model in MODEL_ORDER else len(MODEL_ORDER)
    arm_rank = ARMS.index(arm) if arm in ARMS else len(ARMS)
    return (model_rank, model, arm_rank)


def load_eval(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"eval file must be a JSON object: {path}")
    return data


def is_empty_answer(row: dict[str, Any]) -> bool:
    return not str(row.get("answer_norm") or "").strip()


def scan_file(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[tuple[str, str]]]:
    model = infer_model(path)
    errors: list[dict[str, Any]] = []
    stubborn: list[dict[str, Any]] = []
    seen = {(model, arm) for arm in ARMS}
    data = load_eval(path)
    for qid, by_arm in data.items():
        if not isinstance(by_arm, dict):
            continue
        for arm in ARMS:
            row = by_arm.get(arm)
            if not isinstance(row, dict):
                continue
            api_error = "_api_error" in row
            parse_error = "_parse_error" in row
            empty_answer = is_empty_answer(row)
            record = {
                "model": model,
                "arm": arm,
                "qid": qid,
                "api_error": api_error,
                "parse_error": parse_error,
                "empty_answer": empty_answer,
            }
            if row.get("_stubborn"):
                stubborn.append(record)
                continue
            if api_error or parse_error or empty_answer:
                errors.append(record)
    return errors, stubborn, seen


def qid_list(rows: list[dict[str, Any]]) -> str:
    return ",".join(sorted(str(row["qid"]) for row in rows)) or "-"


def render_report(
    errors: list[dict[str, Any]],
    stubborn: list[dict[str, Any]],
    seen_keys: set[tuple[str, str]],
) -> str:
    lines: list[str] = []
    lines.append("# scan_eval_errors")
    lines.append("")
    lines.append(f"ERRORS={len(errors)}")
    lines.append(f"STUBBORN={len(stubborn)}")
    lines.append("")
    lines.append("## retry-worthy rows (stubborn excluded)")
    lines.append(
        "| model | arm | error_rows | api_error | parse_error | empty_answer | qids |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in errors:
        grouped[(str(row["model"]), str(row["arm"]))].append(row)
    keys = sorted(
        seen_keys | set(grouped) | {(str(row["model"]), str(row["arm"])) for row in stubborn},
        key=sort_key,
    )
    for key in keys:
        rows = grouped.get(key, [])
        lines.append(
            f"| {key[0]} | {key[1]} | {len(rows)} | "
            f"{sum(1 for row in rows if row['api_error'])} | "
            f"{sum(1 for row in rows if row['parse_error'])} | "
            f"{sum(1 for row in rows if row['empty_answer'])} | "
            f"{qid_list(rows)} |"
        )
    if not keys:
        lines.append("| - | - | 0 | 0 | 0 | 0 | - |")
    lines.append("")
    lines.append("## stubborn rows (known safety refusals, excluded from ERRORS)")
    lines.append("| model | arm | stubborn_rows | qids |")
    lines.append("|---|---|---:|---|")
    stubborn_grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in stubborn:
        stubborn_grouped[(str(row["model"]), str(row["arm"]))].append(row)
    for key, rows in sorted(stubborn_grouped.items(), key=lambda item: sort_key(item[0])):
        lines.append(f"| {key[0]} | {key[1]} | {len(rows)} | {qid_list(rows)} |")
    if not stubborn_grouped:
        lines.append("| - | - | 0 | - |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    errors: list[dict[str, Any]] = []
    stubborn: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for path in resolve_files(args):
        file_errors, file_stubborn, file_seen = scan_file(path)
        errors.extend(file_errors)
        stubborn.extend(file_stubborn)
        seen_keys.update(file_seen)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_report(errors, stubborn, seen_keys), encoding="utf-8")
        wrote = 1
    else:
        wrote = 0
    print(f"ERRORS={len(errors)} STUBBORN={len(stubborn)} WROTE={wrote}")


if __name__ == "__main__":
    main()
