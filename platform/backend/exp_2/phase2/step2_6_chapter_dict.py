#!/usr/bin/env python3
"""Phase 2 Step 2.6: Build source_file to chapter_unit dictionary."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from phase2_common import (
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    default_output_path,
    ensure_parent,
    open_driver,
    write_csv,
)


CSV_FIELDNAMES = ["chapter_unit", "category", "node_count", "source_file_count"]

# 題庫/混合類型關鍵詞：不計入覆蓋率
_SKIP_PATTERNS = re.compile(
    r"初級|資訊安全工程師|混合|題庫|exam|practice|test|question",
    re.IGNORECASE,
)


def _normalize_digits(value: str) -> str:
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    return value.translate(table)


def _clean_title(value: str) -> str:
    value = re.sub(r"\.(pdf|json)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[_\s-]*e\d+$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^[\s_-]+|[\s_-]+$", "", value)
    value = re.sub(r"\s+", "", value)
    return value or "未命名"


def _parse_one(source_file: str) -> dict:
    """解析單一 source_file，回傳 {chapter_unit, category, chapter_no(optional)}。"""
    name       = Path(str(source_file)).name
    stem       = re.sub(r"\.(pdf|json)$", "", name, flags=re.IGNORECASE)
    normalized = _normalize_digits(stem)

    # Rule 1: 第N章 format
    m = re.search(r"第\s*(\d{1,2})\s*章[\s_-]*(.+)$", normalized)
    if m:
        chapter_no = int(m.group(1))
        title      = _clean_title(m.group(2))
        return {"chapter_unit": f"{chapter_no:02d}_{title}",
                "category": "章節", "chapter_no": chapter_no}

    # Rule 2: ch\d+_習題解答 → 合併到同章號的第N章
    m = re.match(r"ch(\d{1,2})[\s_-]*習題解答", normalized, re.IGNORECASE)
    if m:
        chapter_no = int(m.group(1))
        return {"chapter_unit": f"{chapter_no:02d}_習題解答",  # 暫用，後續合併
                "category": "章節", "chapter_no": chapter_no, "_is_exercise": True}

    # Rule 3: 模組 format
    m = re.search(r"模組\s*\d+[\s_-]*[-_－:：]?\s*(.+)$", normalized, re.IGNORECASE)
    if "網路安全簡介" in normalized or m:
        title = _clean_title(m.group(1)) if m else _clean_title(
            re.sub(r"^ipas[\s_-]*", "", normalized, flags=re.IGNORECASE))
        return {"chapter_unit": f"M_{title}", "category": "模組"}

    # Rule 4: 題庫/混合 → SKIP（不計覆蓋率）
    if _SKIP_PATTERNS.search(normalized):
        return {"chapter_unit": "SKIP", "category": "題庫"}

    return {"chapter_unit": "UNMATCHED", "category": "UNMATCHED"}


def build_source_mapping(source_files: list[str]) -> dict[str, dict[str, str]]:
    """
    兩階段解析：
    1. 先解析所有 source_file，建立 chapter_no → chapter_unit 的查找表（從第N章格式）
    2. 將習題解答合併到同章號的第N章，找不到對應章節則保留原始 chapter_unit
    """
    raw = {sf: _parse_one(sf) for sf in sorted(source_files)}

    # 第一階段：取得正式章節 chapter_no → chapter_unit 對照
    chapter_no_to_unit: dict[int, str] = {}
    for info in raw.values():
        if info["category"] == "章節" and not info.get("_is_exercise"):
            no = info.get("chapter_no")
            if no is not None:
                chapter_no_to_unit[no] = info["chapter_unit"]

    # 第二階段：合併習題解答
    result: dict[str, dict[str, str]] = {}
    for sf, info in raw.items():
        if info.get("_is_exercise"):
            no = info.get("chapter_no")
            merged_unit = chapter_no_to_unit.get(no, info["chapter_unit"])
            result[sf] = {"chapter_unit": merged_unit, "category": "章節"}
        else:
            result[sf] = {"chapter_unit": info["chapter_unit"],
                          "category":     info["category"]}
    return result


def normalize_source_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    return [str(item).strip() for item in values if str(item).strip()]


def fetch_source_file_nodes(session) -> dict[str, set[int]]:
    result = session.run(
        """
        MATCH (a:KGNode)-[r]->(b:KGNode)
        WHERE r.source_file IS NOT NULL
        RETURN r.source_file AS source_file,
               collect(DISTINCT id(a)) AS source_node_ids,
               collect(DISTINCT id(b)) AS target_node_ids
        """
    )
    source_to_node_ids: dict[str, set[int]] = defaultdict(set)
    for record in result:
        node_ids = set(record["source_node_ids"]) | set(record["target_node_ids"])
        for source_file in normalize_source_values(record["source_file"]):
            source_to_node_ids[source_file].update(node_ids)
    return dict(source_to_node_ids)


def summarize_chapter_counts(
    source_to_chapter: dict[str, dict[str, str]],
    source_to_node_ids: dict[str, set[int]],
) -> list[dict]:
    """
    彙整各 chapter_unit 的節點數與來源檔案數。
    - SKIP（題庫）類型排除，不計入覆蓋率
    - 覆蓋率邏輯：source_file 陣列中任一元素命中即算（OR，已由 fetch_source_file_nodes 展開）
    """
    chapter_to_nodes:   dict[str, set[int]] = defaultdict(set)
    chapter_to_sources: dict[str, set[str]] = defaultdict(set)
    category_map:       dict[str, str]      = {}

    for source_file, info in source_to_chapter.items():
        chapter_unit = info["chapter_unit"]
        category     = info.get("category", "UNMATCHED")
        if chapter_unit == "SKIP":   # 題庫不計入
            continue
        chapter_to_sources[chapter_unit].add(source_file)
        chapter_to_nodes[chapter_unit].update(
            source_to_node_ids.get(source_file, set()))
        category_map[chapter_unit] = category

    rows = []
    for chapter_unit in sorted(chapter_to_sources):
        rows.append({
            "chapter_unit":      chapter_unit,
            "category":          category_map.get(chapter_unit, ""),
            "node_count":        len(chapter_to_nodes[chapter_unit]),
            "source_file_count": len(chapter_to_sources[chapter_unit]),
        })
    return rows


def write_yaml_mapping(path: str | Path, mapping: dict[str, dict[str, str]]) -> Path:
    path = ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        for source_file, info in mapping.items():
            f.write(f"{json.dumps(source_file, ensure_ascii=False)}:\n")
            f.write(f"  chapter_unit: {json.dumps(info['chapter_unit'], ensure_ascii=False)}\n")
            f.write(f"  category: {json.dumps(info['category'], ensure_ascii=False)}\n")
    return path


def execute(
    uri: str,
    user: str,
    password: str,
    output_yaml: str | Path,
    output_csv: str | Path,
) -> tuple[dict, list[dict]]:
    driver = open_driver(uri, user, password)
    try:
        with driver.session() as session:
            source_to_node_ids = fetch_source_file_nodes(session)
    finally:
        driver.close()

    source_to_chapter = build_source_mapping(list(source_to_node_ids))
    rows = summarize_chapter_counts(source_to_chapter, source_to_node_ids)
    write_yaml_mapping(output_yaml, source_to_chapter)
    write_csv(output_csv, CSV_FIELDNAMES, rows)

    # 統計各分類
    from collections import Counter
    cat_counts = Counter(info["category"] for info in source_to_chapter.values())
    print(f"分類統計：{dict(cat_counts)}")

    skipped = [sf for sf, info in source_to_chapter.items() if info["chapter_unit"] == "SKIP"]
    print(f"  題庫（SKIP，不計覆蓋率）：{len(skipped)} 份")

    unmatched = [sf for sf, info in source_to_chapter.items() if info["chapter_unit"] == "UNMATCHED"]
    print(f"  UNMATCHED（需人工確認）：{len(unmatched)} 份")
    for sf in unmatched:
        print(f"    - {sf}")

    print(f"\n有效章節單元數（章節 + 模組）：{len(rows)}")
    print(f"完成：{output_yaml} / {output_csv}")
    return source_to_chapter, rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--user", default=DEFAULT_NEO4J_USER)
    parser.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    parser.add_argument(
        "--output_yaml",
        default=str(default_output_path("source_file_to_chapter.yaml")),
    )
    parser.add_argument(
        "--output_csv",
        default=str(default_output_path("chapter_node_count.csv")),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    execute(args.uri, args.user, args.password, args.output_yaml, args.output_csv)


if __name__ == "__main__":
    main()
