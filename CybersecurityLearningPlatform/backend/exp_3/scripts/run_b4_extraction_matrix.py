"""Run the strict B4 extractor independently for four evaluated models."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
EXP3_DIR = SCRIPT_DIR.parent
BACKEND_DIR = EXP3_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from exp_3.b4.extraction import validate_extraction_artifact
from exp_3.b4.question_normalization import normalize_question_set


FOUR_MODELS = ("e4b", "gptoss", "gemma31b", "llama70b")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", default=",".join(FOUR_MODELS))
    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--linker-config", type=Path)
    parser.add_argument("--embedding-cache", type=Path)
    parser.add_argument("--uri")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    models = tuple(item.strip() for item in args.models.split(",") if item.strip())
    if models != FOUR_MODELS:
        raise RuntimeError(f"B4 extractor matrix must run exactly {FOUR_MODELS}")
    questions = normalize_question_set(json.loads(args.questions.read_text(encoding="utf-8")))
    qids = [question["qid"] for question in questions]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_reports: list[dict] = []
    pipeline = EXP3_DIR / "exp_3_nf1_pipeline.py"
    for model in models:
        output = args.output_dir / f"subgraph_nf1_{model}.json"
        log_path = args.output_dir / f"extract_{model}.log"
        command = [
            sys.executable,
            str(pipeline),
            "--model",
            model,
            "--questions",
            str(args.questions),
            "--output",
            str(output),
        ]
        for flag, value in (
            ("--aliases", args.aliases),
            ("--linker-config", args.linker_config),
            ("--embedding-cache", args.embedding_cache),
            ("--uri", args.uri),
            ("--user", args.user),
            ("--password", args.password),
        ):
            if value:
                command.extend([flag, str(value)])
        if args.workers:
            command.extend(["--n_workers", str(args.workers)])
        if args.limit:
            command.extend(["--limit", str(args.limit)])
        completed = subprocess.run(command, text=True, capture_output=True)
        log_path.write_text(
            f"returncode={completed.returncode}\nSTDOUT\n{completed.stdout}\nSTDERR\n{completed.stderr}\n",
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise RuntimeError(f"extractor failed for {model}; see {log_path}")
        if not output.is_file():
            raise RuntimeError(f"extractor did not produce output for {model}")
        payload = json.loads(output.read_text(encoding="utf-8"))
        report = validate_extraction_artifact(payload, qids=qids, model=model)
        report.update({"output": str(output.resolve()), "sha256": sha256_file(output)})
        model_reports.append(report)

    manifest = {
        "status": "PASS",
        "version": "b4-extractor-matrix-v1",
        "models": list(models),
        "question_count": len(qids),
        "questions_sha256": sha256_file(args.questions),
        "model_reports": model_reports,
        "independent_runs": True,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "models": list(models), "question_count": len(qids)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

