#!/usr/bin/env python
"""Smoke test for the ETL attribution report."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPORT_MODULE_PATH = SCRIPT_PATH.parent / "etl_attribution_report.py"


def load_report_module():
    spec = importlib.util.spec_from_file_location("etl_attribution_report", REPORT_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load attribution report module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    module = load_report_module()
    temp_dir = Path(tempfile.mkdtemp(prefix="attrib_report_"))
    try:
        audit_path = temp_dir / "audit.jsonl"
        matchgpt_path = temp_dir / "matchgpt.csv"
        out_path = temp_dir / "report.md"

        write_jsonl(
            audit_path,
            [
                {
                    "decision": "reject",
                    "stage": "phase1_schema",
                    "reason_summary": "bad schema",
                    "raw_triple": {
                        "subject": {"name": "a", "type": "vulnerability"},
                        "relation": "controls",
                        "object": {"name": "b", "type": "system"},
                    },
                },
                {
                    "decision": "accept",
                    "stage": "step3_semantic",
                    "reason_summary": "accepted",
                    "raw_triple": {
                        "subject": {"name": "scanner", "type": "tool"},
                        "relation": "uses",
                        "object": {"name": "signature", "type": "technique"},
                    },
                },
                {
                    "decision": "reject",
                    "stage": "neo4j_import",
                    "reason_summary": "write failed",
                    "raw_triple": {
                        "subject": {"name": "x", "type": "tool"},
                        "relation": "uses",
                        "object": {"name": "y", "type": "technique"},
                    },
                },
            ],
        )
        matchgpt_path.write_text(
            "name_a,type_a,name_b,type_b,similarity,confidence,reason\n"
            "alpha,tool,alpha tool,tool,0.99,0.9,same entity\n"
            "beta,feature,beta feature,feature,0.95,0.8,same entity\n",
            encoding="utf-8",
        )

        rc = module.main(
            [
                "--audit-log",
                str(audit_path),
                "--matchgpt-csv",
                str(matchgpt_path),
                "--out",
                str(out_path),
            ]
        )
        assert rc == 0
        report = out_path.read_text(encoding="utf-8")
        assert "candidate_triples_count: 3" in report
        assert "accepted_triples_count: 1" in report
        assert "validation_rejected_count: 1" in report
        assert "synonym_merged_count: 2" in report
        assert "cross_type_blocked_count: 0" in report
        assert "other_count: 1" in report
        assert "cross_type_data_gap: true" in report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("OK attribution_report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
