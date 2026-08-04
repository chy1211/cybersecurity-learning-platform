"""Freeze and heldout-result preflight for B4."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from exp_3.b4.preflight import (
    build_freeze_manifest,
    sha256_file,
    validate_result_matrix,
    verify_freeze_manifest,
)
from exp_3.b4.question_normalization import normalize_question_set


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def do_freeze(args: argparse.Namespace) -> dict:
    # Route 2 (2026-07-12): no human threshold/margin calibration and no manual
    # alias approval, so there is no "frozen" status to assert.  The freeze lock
    # is the sha256 manifest itself: every artifact below is hashed and any later
    # edit fails verify_freeze_manifest.  The linker config is still hashed (it is
    # static); the alias file is optional.
    required = {
        "formal_questions": args.formal_questions,
        "smoke_questions": args.smoke_questions,
        "smoke_manifest": args.smoke_manifest,
        "linker_config": args.linker_config,
    }
    missing = [name for name, path in required.items() if not path or not path.is_file()]
    if missing:
        raise RuntimeError(f"freeze artifacts missing: {missing}")
    if not args.prompt:
        raise RuntimeError("freeze requires at least one frozen prompt path")
    formal = normalize_question_set(
        json.loads(args.formal_questions.read_text(encoding="utf-8"))
    )
    if len(formal) != 356:
        raise RuntimeError(f"formal heldout set must contain 356 questions, got {len(formal)}")
    smoke = json.loads(args.smoke_manifest.read_text(encoding="utf-8"))
    if smoke.get("count") != 5 or smoke.get("heldout_used"):
        raise RuntimeError("smoke manifest is not the fixed five-question construction artifact")
    paths = [
        args.formal_questions,
        args.smoke_questions,
        args.smoke_manifest,
        args.linker_config,
        *([args.aliases] if args.aliases and args.aliases.is_file() else []),
        *args.prompt,
    ]
    manifest = build_freeze_manifest(
        paths,
        metadata={
            "experiment": "B4-correctness-first-retrieval",
            "formal_question_count": len(formal),
            "smoke_question_count": 5,
            "conditions": ["base", "rag"],
            "models": args.models.split(","),
            "expected_answer_records": 4 * 356 * 2,
        },
    )
    write_json(args.output, manifest)
    return manifest


def do_results(args: argparse.Namespace) -> dict:
    if args.freeze_manifest:
        freeze = verify_freeze_manifest(args.freeze_manifest)
    else:
        freeze = None
    questions = normalize_question_set(json.loads(args.questions.read_text(encoding="utf-8")))
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    conditions = [item.strip() for item in args.conditions.split(",") if item.strip()]
    result_by_model: dict[str, dict] = {}
    missing_files = []
    for model in models:
        path = args.results_dir / f"eval_{model}{args.suffix}.json"
        if not path.is_file():
            missing_files.append(str(path))
            continue
        result_by_model[model] = json.loads(path.read_text(encoding="utf-8"))
    if missing_files:
        raise RuntimeError(f"missing model result files: {missing_files}")
    report = validate_result_matrix(
        result_by_model,
        qids=[question["qid"] for question in questions],
        models=models,
        conditions=conditions,
    )
    report["freeze_manifest_sha256"] = (
        sha256_file(args.freeze_manifest) if args.freeze_manifest else None
    )
    report["freeze_verified"] = freeze is not None
    write_json(args.output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["freeze", "results"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", default="e4b,gptoss,gemma31b,llama70b")
    parser.add_argument("--conditions", default="base,rag")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--formal-questions", type=Path)
    parser.add_argument("--smoke-questions", type=Path)
    parser.add_argument("--smoke-manifest", type=Path)
    parser.add_argument("--linker-config", type=Path)
    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--prompt", type=Path, action="append", default=[])
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--freeze-manifest", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        do_freeze(args)
        print(json.dumps({"status": "FROZEN", "output": str(args.output)}))
    else:
        if not args.questions or not args.results_dir:
            raise RuntimeError("results mode requires --questions and --results-dir")
        report = do_results(args)
        print(json.dumps({"status": report["status"], "expected_records": report["expected_records"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
