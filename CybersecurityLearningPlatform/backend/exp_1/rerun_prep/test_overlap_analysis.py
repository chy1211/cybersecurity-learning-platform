#!/usr/bin/env python
"""Smoke tests for overlap_analysis.py."""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
MODULE_PATH = SCRIPT_PATH.parent / "overlap_analysis.py"


def load_module():
    spec = importlib.util.spec_from_file_location("overlap_analysis", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load overlap_analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    module = load_module()
    temp_dir = Path(tempfile.mkdtemp(prefix="overlap_analysis_"))
    try:
        assert module.normalize_for_match(" SQL　Injection ") == "sqlinjection"
        assert module.normalize_for_match("社 交　工程") == "社交工程"

        matched = module.match_entities_in_text(
            ["SQL Injection", "社交工程", "A", "DoS"],
            "這題提到社 交工程，也提到 sql injection，但不應把單一 A 算成知識點。",
        )
        assert matched == {"SQL Injection", "社交工程"}

        ite_path = temp_dir / "ite.json"
        write_json(
            ite_path,
            [
                {
                    "qid": "ISN-107-001",
                    "stem": "SQL Injection 是哪一類攻擊？",
                    "options": {"A": "弱點利用", "B": "備份"},
                },
                {
                    "qid": "CUSTOM-001",
                    "stem": "自製題應排除",
                    "options": {"A": "自製"},
                },
                {
                    "qid": "ISK-108-002",
                    "stem": "社交工程與存取控制",
                    "options": ["機密性", "可用性"],
                },
            ],
        )
        ite_docs = module.load_ite_texts(ite_path)
        assert len(ite_docs) == 2
        assert "CUSTOM" not in "\n".join(ite_docs)
        assert "SQL Injection" in ite_docs[0]
        assert "存取控制" in ite_docs[1]

        csv_path = temp_dir / "matchgpt_merged_t07.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name_a", "type_a", "name_b", "type_b"])
            writer.writeheader()
            writer.writerow({"name_a": "SQL Injection", "type_a": "technique", "name_b": "SQL Injection 攻擊", "type_b": "technique"})
            writer.writerow({"name_a": "A", "type_a": "feature", "name_b": "社交工程", "type_b": "technique"})
        vocab = module.load_fallback_vocabulary([csv_path])
        assert vocab.source == "fallback"
        assert vocab.source_detail.endswith("matchgpt_merged_t07.csv")
        assert vocab.entities == ["SQL Injection", "SQL Injection 攻擊", "社交工程"]

        result = module.analyze_overlap(
            vocabulary=["SQL Injection", "SQL Injection 攻擊", "社交工程", "存取控制", "A"],
            source_texts={
                "ite": ["SQL Injection 與存取控制"],
                "ipas": ["社交工程與 SQL Injection 攻擊"],
            },
            dry_run_note="DRY-RUN test note",
            vocabulary_source="fallback",
            vocabulary_source_detail=str(csv_path),
        )
        assert result["sources"]["ite"]["knowledge_point_count"] == 2
        assert result["sources"]["ipas"]["knowledge_point_count"] == 3
        pair = result["pairwise"]["ite__ipas"]
        assert pair["a_count"] == 2
        assert pair["b_count"] == 3
        assert pair["common_count"] == 1
        assert pair["jaccard"] == 0.25
        assert pair["common_examples"] == ["SQL Injection"]
        assert pair["a_only_examples"] == ["存取控制"]
        assert "社交工程" in pair["b_only_examples"]

        out_path = temp_dir / "overlap.txt"
        details_path = temp_dir / "overlap.json"
        module.write_report(result, out_path)
        module.write_details(result, details_path)
        report = out_path.read_text(encoding="utf-8")
        assert "DRY-RUN test note" in report
        assert "| ite | ipas | 2 | 3 | 1 | 0.2500 |" in report
        details = json.loads(details_path.read_text(encoding="utf-8"))
        assert details["pairwise"]["ite__ipas"]["common_count"] == 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("OK overlap_analysis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
