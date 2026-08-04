"""Run the fixed five-question retrieval and answer smoke gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
EXP3_DIR = SCRIPT_DIR.parent
BACKEND_DIR = EXP3_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from exp_3.b4.extraction import validate_extraction_artifact
from exp_3.b4.preflight import validate_result_matrix
from exp_3.b4.question_normalization import normalize_question_set


MODELS = ("e4b", "gptoss", "gemma31b", "llama70b")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_environment(models: tuple[str, ...]) -> list[dict]:
    checks: list[dict] = []
    for model in models:
        if model in {"e4b", "gptoss"}:
            configured = bool(
                os.getenv("LM_STUDIO_CHAT_URL")
                or os.getenv("LM_STUDIO_CHAT_URL_ALT")
                or "http://127.0.0.1:1234/v1/chat/completions"
            )
            identity = "LM Studio: e4b/gptoss model identity checked by live call"
        elif model == "gemma31b":
            configured = bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GOOGLE_API_KEYS"))
            identity = "Google AI Studio: gemma-4-31b-it"
        elif model == "llama70b":
            configured = any(
                key.startswith("NVIDIA_API_KEY_") and value.strip()
                for key, value in os.environ.items()
            )
            identity = "NVIDIA: meta/llama-3.1-70b-instruct"
        else:
            configured = False
            identity = "unknown"
        checks.append({"model": model, "configured": configured, "identity": identity})
    missing = [item["model"] for item in checks if not item["configured"]]
    if missing:
        raise RuntimeError(f"smoke environment missing endpoint/key configuration: {missing}")
    return checks


def check_retrieval(args: argparse.Namespace, questions: list[dict]) -> dict:
    qids = [question["qid"] for question in questions]
    reports = []
    for model in MODELS:
        path = Path(args.subgraphs.replace("{model}", model))
        if not path.is_file():
            raise RuntimeError(f"retrieval smoke artifact missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports.append(validate_extraction_artifact(payload, qids=qids, model=model))
    return {"status": "PASS", "models": reports}


def check_answer(args: argparse.Namespace, questions: list[dict], output_dir: Path) -> dict:
    check_environment(MODELS)
    command = [
        sys.executable,
        str(EXP3_DIR / "exp_3_eval_batch.py"),
        "--questions",
        str(args.questions),
        "--subgraphs",
        args.subgraphs,
        "--output_dir",
        str(output_dir),
        "--models",
        ",".join(MODELS),
        "--conditions",
        "base,rag",
        "--workers_per_model",
        "1",
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    log = output_dir / "answer_smoke.log"
    log.write_text(
        f"returncode={completed.returncode}\nSTDOUT\n{completed.stdout}\nSTDERR\n{completed.stderr}\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"answer smoke failed; see {log}")
    results = {
        model: json.loads((output_dir / f"eval_{model}.json").read_text(encoding="utf-8"))
        for model in MODELS
    }
    report = validate_result_matrix(
        results,
        qids=[question["qid"] for question in questions],
        models=MODELS,
        conditions=("base", "rag"),
    )
    report["live_endpoint_check"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["retrieval", "answer", "all"], default="all")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--smoke-manifest", type=Path, required=True)
    parser.add_argument("--subgraphs", required=True, help="path template containing {model}")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    questions = normalize_question_set(json.loads(args.questions.read_text(encoding="utf-8")))
    smoke_manifest = json.loads(args.smoke_manifest.read_text(encoding="utf-8"))
    if len(questions) != 5 or smoke_manifest.get("count") != 5:
        raise RuntimeError("B4 smoke requires exactly five questions")
    if smoke_manifest.get("questions_sha256") != sha256_file(args.questions):
        raise RuntimeError("smoke question file hash does not match frozen manifest")

    report = {
        "version": "b4-smoke-run-v1",
        "models": list(MODELS),
        "question_sha256": sha256_file(args.questions),
        "environment": (
            check_environment(MODELS)
            if args.phase in {"answer", "all"}
            else {"status": "not_run", "reason": "retrieval-only smoke"}
        ),
    }
    if args.phase in {"retrieval", "all"}:
        report["retrieval"] = check_retrieval(args, questions)
    if args.phase in {"answer", "all"}:
        if "retrieval" not in report:
            report["retrieval"] = check_retrieval(args, questions)
        if report["retrieval"]["status"] != "PASS":
            raise RuntimeError("answer smoke is blocked by retrieval smoke")
        report["answer"] = check_answer(args, questions, args.output_dir)
    report["status"] = "PASS"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "phase": args.phase, "models": list(MODELS)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
