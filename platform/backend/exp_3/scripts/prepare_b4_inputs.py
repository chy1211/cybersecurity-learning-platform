"""Build the immutable B4 normalized held-out input artifacts.

Usage from the handoff backend directory:
    python exp_3/scripts/prepare_b4_inputs.py \
      --heldout PATH_TO_HELDOUT_JSON \
      --construction PATH_TO_CONSTRUCTION_JSON \
      --output-dir PATH_TO_B4_INPUT_DIR

This script never overwrites the source JSON files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from exp_3.b4.question_normalization import (  # noqa: E402
    EXCLUDED_VISUAL_QUESTIONS,
    normalize_question_set,
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_heldout_artifacts(
    heldout_path: Path,
    output_dir: Path,
    construction_path: Path | None = None,
) -> dict:
    raw = read_json(heldout_path)
    if not isinstance(raw, list):
        raise ValueError("heldout input must be a JSON array")
    normalized = normalize_question_set(raw)
    raw_by_qid = {record.get("qid") or record.get("id"): record for record in raw}
    all_qids = {record["qid"] for record in normalized}
    excluded_qids = set(EXCLUDED_VISUAL_QUESTIONS)
    missing_excluded = excluded_qids - all_qids
    if missing_excluded:
        raise ValueError(f"excluded qids missing from source: {sorted(missing_excluded)}")

    formal = [record for record in normalized if record["qid"] not in excluded_qids]
    formal_qids = {record["qid"] for record in formal}
    if len(normalized) != 364 or len(formal) != 356:
        raise ValueError(
            f"unexpected heldout counts: input={len(normalized)}, formal={len(formal)}"
        )
    if formal_qids & excluded_qids:
        raise ValueError("formal and excluded qid sets overlap")
    if formal_qids | excluded_qids != all_qids:
        raise ValueError("formal plus excluded qids do not reconstruct input qids")
    source_counts = Counter(record["source"] for record in formal)
    if source_counts != Counter({"iPAS": 323, "ISN": 33}):
        raise ValueError(f"unexpected formal source counts: {dict(source_counts)}")

    excluded_manifest = []
    for qid, details in EXCLUDED_VISUAL_QUESTIONS.items():
        excluded_manifest.append(
            {
                "qid": qid,
                "source_file": str(heldout_path),
                "reason": details["reason"],
                "visual_dependency": details["visual_dependency"],
                "source_record_present": qid in raw_by_qid,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    formal_path = output_dir / "heldout_test_set_b4_356.json"
    excluded_path = output_dir / "excluded_visual_questions.json"
    report_path = output_dir / "normalization_report.json"
    write_json(formal_path, formal)
    write_json(excluded_path, excluded_manifest)

    report = {
        "source_path": str(heldout_path.resolve()),
        "source_sha256": sha256_file(heldout_path),
        "input_count": len(normalized),
        "output_count": len(formal),
        "excluded_count": len(excluded_manifest),
        "input_source_counts": dict(Counter(record["source"] for record in normalized)),
        "output_source_counts": dict(source_counts),
        "excluded_qids": sorted(excluded_qids),
        "formal_qid_count_unique": len(formal_qids) == len(formal),
        "reconstructs_input_qids": formal_qids | excluded_qids == all_qids,
        "all_single_choice": all(record["is_single"] for record in formal),
        "options_are_a_to_d": all(set(record["options"]) == {"A", "B", "C", "D"} for record in formal),
        "formal_output_sha256": sha256_file(formal_path),
    }
    if construction_path is not None:
        raw_construction = read_json(construction_path)
        if not isinstance(raw_construction, list):
            raise ValueError("construction input must be a JSON array")
        construction = normalize_question_set(raw_construction)
        construction_counts = Counter(record["source"] for record in construction)
        if len(construction) != 854:
            raise ValueError(f"unexpected construction count: {len(construction)}")
        if construction_counts != Counter({"iPAS": 770, "ISN": 84}):
            raise ValueError(
                f"unexpected construction source counts: {dict(construction_counts)}"
            )
        construction_output = output_dir / "construction_set_b4_854.json"
        write_json(construction_output, construction)
        report["construction"] = {
            "source_path": str(construction_path.resolve()),
            "source_sha256": sha256_file(construction_path),
            "input_count": len(construction),
            "source_counts": dict(construction_counts),
            "output_path": str(construction_output.resolve()),
            "output_sha256": sha256_file(construction_output),
        }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--construction", type=Path, required=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_heldout_artifacts(args.heldout, args.output_dir, args.construction)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
