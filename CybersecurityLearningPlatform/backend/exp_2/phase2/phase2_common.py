#!/usr/bin/env python3
"""Shared helpers for Phase 2 graph-structuring scripts."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Load backend .env when this script is executed directly.
try:
    from dotenv import load_dotenv as _load_dotenv
    for _env_parent in Path(__file__).resolve().parents:
        _env_file = _env_parent / ".env"
        if _env_file.exists():
            _load_dotenv(_env_file)
            break
except Exception:
    pass


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parents[1]
THESIS_DIR = SCRIPT_DIR.parents[3]
DEFAULT_RESULT_DIR = THESIS_DIR / "實驗" / "Phase2_圖譜結構化" / "結果"

DEFAULT_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
DEFAULT_BATCH_SIZE = 200

# 平台格式：16 種語意關係（safe label，alphanum only）
# 供 GDS graph.project 投影使用
PLATFORM_REL_TYPES = [
    "has_a", "can_analyze", "can_expose", "can_exploit", "implements",
    "uses", "can_harm", "can_detect", "is_part_of", "mitigates",
    "violates", "deployed_in", "generates", "connects_to", "depends_on", "controls",
]

def platform_rel_projection(orientation: str = "UNDIRECTED") -> dict:
    """供 GDS graph.project 使用的關係投影 dict（所有平台格式關係類型）。"""
    return {rt: {"orientation": orientation} for rt in PLATFORM_REL_TYPES}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_output_path(filename: str) -> Path:
    return DEFAULT_RESULT_DIR / filename


def ensure_parent(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def open_driver(uri: str, user: str, password: str):
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=(user, password))


def write_json(path: str | Path, payload: dict) -> Path:
    path = ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def write_csv(path: str | Path, fieldnames: list[str], rows: Iterable[dict]) -> Path:
    path = ensure_parent(path)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def read_csv(path: str | Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def batch_write(session, cypher: str, rows: list[dict], batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    total = len(rows)
    for start in range(0, total, batch_size):
        session.run(cypher, rows=rows[start : start + batch_size])
    return total


def drop_gds_graph(session, graph_name: str) -> None:
    try:
        session.run("CALL gds.graph.drop($graphName, false)", graphName=graph_name)
    except Exception as exc:
        print(f"  [WARN] drop graph {graph_name} failed: {exc}")


def cid_sort_key(cid):
    if isinstance(cid, (int, float)):
        return (0, float(cid))
    text = str(cid)
    try:
        return (0, float(text))
    except ValueError:
        return (1, text)


def parse_cid(value: str):
    text = str(value).strip()
    if text == "":
        return text
    try:
        as_float = float(text)
        if as_float.is_integer():
            return int(as_float)
        return as_float
    except ValueError:
        return text


