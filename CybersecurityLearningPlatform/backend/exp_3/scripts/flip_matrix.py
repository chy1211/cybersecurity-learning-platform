#!/usr/bin/env python3
"""Build llm_only versus graph_rag flip matrices for exp_3 eval files."""
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
DEFAULT_QB = ROOT / "data" / "question_bank_329.json"
KNOWN_MODELS = ("llama70b", "gemma31b", "gptoss", "llama8b", "gemma", "e4b", "phi")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute 2x2 correctness flip matrices for eval results."
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


def matrix_for(eval_path: Path, qb: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    data = load_json(eval_path)
    if not isinstance(data, dict):
        raise ValueError(f"eval file must be a JSON object: {eval_path}")
    result = {
        "single": {"TT": 0, "TF": 0, "FT": 0, "FF": 0, "TF_qids": [], "FT_qids": []},
        "multiple": {"TT": 0, "TF": 0, "FT": 0, "FF": 0, "TF_qids": [], "FT_qids": []},
    }
    for qid, by_arm in data.items():
        q = qb.get(str(qid))
        if not q or not isinstance(by_arm, dict):
            continue
        llm = by_arm.get("llm_only")
        rag = by_arm.get("graph_rag")
        if not isinstance(llm, dict) or not isinstance(rag, dict):
            continue
        label = "single" if bool(q.get("is_single")) else "multiple"
        llm_ok = bool(llm.get("correct"))
        rag_ok = bool(rag.get("correct"))
        key = ("T" if llm_ok else "F") + ("T" if rag_ok else "F")
        result[label][key] += 1
        if key == "TF":
            result[label]["TF_qids"].append(str(qid))
        elif key == "FT":
            result[label]["FT_qids"].append(str(qid))
    return result


def join_qids(qids: list[str]) -> str:
    return ",".join(sorted(qids)) or "-"


def render(files: list[Path], qb: dict[str, dict[str, Any]]) -> str:
    matrices: dict[str, dict[str, dict[str, Any]]] = {}
    for path in files:
        matrices[infer_model(path)] = matrix_for(path, qb)

    lines = [
        "# flip_matrix",
        "",
        "## matrix",
        "| model | type | correct_to_correct | correct_to_wrong | wrong_to_correct | wrong_to_wrong |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for model, by_type in sorted(matrices.items()):
        for type_label in ("single", "multiple"):
            matrix = by_type[type_label]
            lines.append(
                f"| {model} | {type_label} | {matrix['TT']} | {matrix['TF']} | "
                f"{matrix['FT']} | {matrix['FF']} |"
            )
    lines.extend(
        [
            "",
            "## flip_qids",
            "| model | type | direction | n | qids |",
            "|---|---|---|---:|---|",
        ]
    )
    for model, by_type in sorted(matrices.items()):
        for type_label in ("single", "multiple"):
            matrix = by_type[type_label]
            directions = {
                "wrong_to_correct": matrix["FT_qids"],
                "correct_to_wrong": matrix["TF_qids"],
            }
            for direction, qids in directions.items():
                lines.append(
                    f"| {model} | {type_label} | {direction} | {len(qids)} | {join_qids(qids)} |"
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
    print(f"WROTE=1 ROWS={len(files) * 2}")


if __name__ == "__main__":
    main()
