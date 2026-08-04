"""Build and freeze the five-question B4 construction smoke set."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parents[1]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--construction", type=Path, required=True)
    parser.add_argument(
        "--cases",
        type=Path,
        default=BACKEND_DIR / "exp_3" / "config" / "b4_smoke_cases.json",
    )
    parser.add_argument("--output-questions", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    args = parser.parse_args()

    construction_bytes = args.construction.read_bytes()
    construction = json.loads(construction_bytes.decode("utf-8"))
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(construction, list) or not isinstance(cases, list):
        raise ValueError("construction and smoke cases must be JSON arrays")
    if len(cases) != 5:
        raise ValueError("B4 smoke set must contain exactly five cases")
    qids = [str(case.get("qid") or "") for case in cases]
    if len(set(qids)) != 5 or any(not qid for qid in qids):
        raise ValueError("B4 smoke case qids must be unique and non-empty")
    by_qid = {str(question.get("qid") or question.get("id") or ""): question for question in construction}
    missing = [qid for qid in qids if qid not in by_qid]
    if missing:
        raise ValueError(f"smoke qids are not in construction set: {missing}")

    questions = [by_qid[qid] for qid in qids]
    question_bytes = json.dumps(questions, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    manifest = {
        "version": "b4-smoke-v1",
        "count": 5,
        "qids": qids,
        "cases": cases,
        "construction_sha256": sha256_bytes(construction_bytes),
        "case_spec_sha256": sha256_bytes(canonical_json(cases)),
        "questions_sha256": sha256_bytes(question_bytes),
        "heldout_used": False,
    }
    args.output_questions.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_questions.write_bytes(question_bytes)
    args.output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"count": 5, "qids": qids, "questions_sha256": manifest["questions_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

