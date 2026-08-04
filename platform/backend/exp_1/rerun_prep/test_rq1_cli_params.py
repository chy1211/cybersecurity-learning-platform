#!/usr/bin/env python
"""Smoke test for RQ1 report CLI graph-source parameters."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[2]
RQ1_MODULE_PATH = BACKEND_DIR / "exp_1" / "rq1_ontology_usage_report.py"


def load_rq1_module():
    spec = importlib.util.spec_from_file_location("rq1_ontology_usage_report", RQ1_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load RQ1 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_rq1_module()
    args = module.parse_args(
        [
            "--uri",
            "bolt://example.invalid:7687",
            "--db",
            "neo4j",
            "--out",
            "_tooling/rerun_test/rq1_cli_params.txt",
        ]
    )
    assert args.neo4j_uri == "bolt://example.invalid:7687"
    assert args.database == "neo4j"
    print("OK rq1_cli_params")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
