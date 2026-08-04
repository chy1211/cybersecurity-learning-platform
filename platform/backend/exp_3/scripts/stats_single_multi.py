#!/usr/bin/env python3
"""Compute full, single-choice, and multiple-choice accuracy for exp_3 eval files."""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOB = ROOT / "data" / "eval_results" / "eval_*_NF1.json"
DEFAULT_QB = ROOT / "data" / "question_bank_329.json"
KNOWN_MODELS = ("llama70b", "gemma31b", "gptoss", "llama8b", "gemma", "e4b", "phi")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute single/multiple accuracy deltas for eval results."
    )
    parser.add_argument("--glob", default=str(DEFAULT_GLOB))
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--question-bank", default=str(DEFAULT_QB))
    parser.add_argument("--output", required=True)
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
    return sorted(files, key=lambda path: infer_model(path))


def infer_model(path: Path) -> str:
    stem = path.stem
    if stem.startswith("eval_"):
        stem = stem[5:]
    for model in KNOWN_MODELS:
        if stem == model or stem.startswith(model + "_"):
            return model
    match = re.match(r"([A-Za-z0-9-]+)", stem)
    return match.group(1) if match else stem


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_question_bank(path: Path) -> dict[str, dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, list):
        raise ValueError("question bank must be a JSON list")
    return {str(item["qid"]): item for item in data}


def joined_rows(eval_path: Path, qb: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    data = load_json(eval_path)
    if not isinstance(data, dict):
        raise ValueError(f"eval file must be a JSON object: {eval_path}")
    rows: list[dict[str, Any]] = []
    for qid, by_arm in data.items():
        q = qb.get(str(qid))
        if not q or not isinstance(by_arm, dict):
            continue
        llm = by_arm.get("llm_only")
        rag = by_arm.get("graph_rag")
        if not isinstance(llm, dict) or not isinstance(rag, dict):
            continue
        rows.append(
            {
                "qid": str(qid),
                "is_single": bool(q.get("is_single")),
                "llm_only": llm,
                "graph_rag": rag,
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    n = len(rows)
    llm_ok = sum(1 for row in rows if row["llm_only"].get("correct"))
    rag_ok = sum(1 for row in rows if row["graph_rag"].get("correct"))
    llm_acc = 100.0 * llm_ok / n if n else 0.0
    rag_acc = 100.0 * rag_ok / n if n else 0.0
    return {
        "n": n,
        "llm_ok": llm_ok,
        "rag_ok": rag_ok,
        "llm_acc": llm_acc,
        "rag_acc": rag_acc,
        "delta": rag_acc - llm_acc,
    }


def fmt_pct(value: float | int) -> str:
    return f"{float(value):.2f}"


def fmt_delta(value: float | int) -> str:
    return f"{float(value):+.2f}"


def render(files: list[Path], qb: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# stats_single_multi",
        "",
        "| model | slice | n | llm_correct | llm_acc_pct | graph_rag_correct | graph_rag_acc_pct | delta_pp |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for path in files:
        model = infer_model(path)
        rows = joined_rows(path, qb)
        slices = [
            ("all", rows),
            ("single", [row for row in rows if row["is_single"]]),
            ("multiple", [row for row in rows if not row["is_single"]]),
        ]
        for label, slice_rows in slices:
            stats = summarize(slice_rows)
            lines.append(
                f"| {model} | {label} | {stats['n']} | {stats['llm_ok']} | "
                f"{fmt_pct(stats['llm_acc'])} | {stats['rag_ok']} | "
                f"{fmt_pct(stats['rag_acc'])} | {fmt_delta(stats['delta'])} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    files = resolve_files(args)
    qb = load_question_bank(Path(args.question_bank))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(files, qb), encoding="utf-8")
    print(f"WROTE=1 ROWS={len(files) * 3}")


if __name__ == "__main__":
    main()
