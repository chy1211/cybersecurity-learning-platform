#!/usr/bin/env python
"""Smoke test for the ETL validation audit hook.

This test avoids LLM calls and Neo4j writes by monkeypatching the imported
validation module. It intentionally writes one reusable sample audit jsonl under
_tooling/rerun_test for rerun-prep evidence.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path


os.environ.setdefault("NVIDIA_API_KEY_1", "dummy-key-for-import-only")

SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[2]
WORKSPACE_DIR = SCRIPT_PATH.parents[6]
ETL_MODULE_PATH = BACKEND_DIR / "ETL_module" / "03_validate_and_import_fixed.py"
SAMPLE_AUDIT_PATH = WORKSPACE_DIR / "_tooling" / "rerun_test" / "validation_audit_sample.jsonl"


class EmptyResult:
    def single(self):
        return None

    def __iter__(self):
        return iter(())


class FakeSession:
    def run(self, *args, **kwargs):
        return EmptyResult()


def load_etl_module():
    spec = importlib.util.spec_from_file_location("etl03_audit_test_target", ETL_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load ETL validation module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_stubs(module):
    module.call_llama = lambda prompt: '{"response":"correct","reason":"stubbed"}'
    module.queryForDuplicateResources = lambda *args, **kwargs: []
    module.resolve_type_conflict = lambda session, entity_name, current_type: current_type
    module.import_to_neo4j = lambda session, triple: None


def run_one(module, triple, index=0):
    module.step2_next_idx = index
    module.session_entity_cache.clear()
    return module.validate_audit_and_import_triple(
        copy.deepcopy(triple),
        FakeSession(),
        index,
        source_file="unit_raw.json",
    )


def assert_audit_record_shape(record):
    required = {
        "timestamp",
        "decision",
        "stage",
        "reason",
        "reason_summary",
        "source_file",
        "source_index",
        "raw_triple",
        "final_triple",
    }
    missing = sorted(required.difference(record))
    assert not missing, f"missing audit fields: {missing}"
    assert record["decision"] in {"accept", "reject"}
    assert record["stage"] in {
        "phase1_schema",
        "step1_class_property",
        "step2_uri",
        "step3_semantic",
        "neo4j_import",
        "other",
    }
    assert isinstance(record["raw_triple"], dict)
    assert isinstance(record["final_triple"], dict)


def main() -> int:
    module = load_etl_module()
    install_stubs(module)

    default_audit = Path(module.configure_audit_log())
    assert default_audit.parent.name == "logs"
    assert default_audit.name.startswith("validation_audit_")
    assert default_audit.suffix == ".jsonl"

    SAMPLE_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SAMPLE_AUDIT_PATH.exists():
        SAMPLE_AUDIT_PATH.unlink()
    module.configure_audit_log(SAMPLE_AUDIT_PATH)

    phase1_reject = {
        "subject": {"name": "passive flaw", "type": "vulnerability"},
        "relation": "controls",
        "object": {"name": "linux server", "type": "system"},
        "source_file": "unit_raw.json",
        "source_index": 1,
    }
    accepted = {
        "subject": {"name": "scanner", "type": "tool"},
        "relation": "uses",
        "object": {"name": "signature matching", "type": "technique"},
        "source_file": "unit_raw.json",
        "source_index": 2,
    }

    reject_valid, _ = run_one(module, phase1_reject)
    accept_valid, _ = run_one(module, accepted)
    assert reject_valid is False
    assert accept_valid is True

    records = [json.loads(line) for line in SAMPLE_AUDIT_PATH.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    for record in records:
        assert_audit_record_shape(record)
    assert records[0]["decision"] == "reject"
    assert records[0]["stage"] == "phase1_schema"
    assert records[1]["decision"] == "accept"
    assert records[1]["stage"] == "step3_semantic"

    temp_dir = Path(tempfile.mkdtemp(prefix="audit_unwritable_"))
    try:
        unwritable_target = temp_dir / "directory_not_file"
        unwritable_target.mkdir()
        module.configure_audit_log(unwritable_target)
        still_valid, _ = run_one(module, accepted)
        assert still_valid is True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"OK audit_hook records={len(records)} unwritable_continues=1")
    print(f"SAMPLE_AUDIT={SAMPLE_AUDIT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
