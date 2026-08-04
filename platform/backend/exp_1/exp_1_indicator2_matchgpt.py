#!/usr/bin/env python3
"""
實驗 1 指標二：MatchGPT 進階節點整併三層自動指標

讀取 Phase 1 步驟 1.4 產出的 matchgpt_3layer_summary.json 與
matchgpt_decisions.csv，格式化三層指標表（對應論文表 4-7 之 MatchGPT 部分）。

三層指標說明：
  Layer 1（結構性）  : node_count / rel_count / wcc_count / avg_degree /
                      leiden_modularity / node_reduction_ratio
  Layer 2（本體論一致性）: cross_type_merge_rate / relation_preservation_rate
  Layer 3（參數敏感性）  : 相鄰 threshold 間的指標差值

輸入欄位對應（支援兩種格式）：
  1. prompt 規格：
     thresholds: [0.5, 0.7, 0.9]
     structural: [{threshold, node_count, relation_count/rel_count, wcc_count,
                   avg_degree, leiden_modularity, node_reduction_ratio}, ...]
     ontology_consistency: [{threshold, pairs_filtered, merged_pairs,
                             cross_category_merge_rate/cross_type_merge_rate,
                             relation_preservation_rate}, ...]
  2. Phase 1 legacy 格式：
     layer1_structural[tX.X], layer2_ontology_consistency[tX.X],
     layer3_parameter_sensitivity[tA_vs_tB]

用法：
  python exp_1_indicator2_matchgpt.py \\
    --summary   path/to/matchgpt_3layer_summary.json \\
    --decisions path/to/matchgpt_decisions.csv \\
    --output    路徑/indicator2_matchgpt_metrics.json
"""

import argparse
import csv
import json
from datetime import datetime
from itertools import combinations
from pathlib import Path


DEFAULT_THRESHOLDS = ["t0.5", "t0.7", "t0.9"]

STRUCTURAL_ALIASES = {
    "node_count": ["node_count", "nodes", "node_total"],
    "rel_count": ["rel_count", "relation_count", "relationship_count", "edge_count"],
    "wcc_count": [
        "wcc_count", "weak_connected_component_count",
        "weakly_connected_component_count", "weakly_connected_components",
    ],
    "avg_degree": ["avg_degree", "average_degree", "mean_degree"],
    "leiden_modularity": [
        "leiden_modularity", "leiden_modularity_gamma1", "modularity",
    ],
    "node_reduction_ratio": [
        "node_reduction_ratio", "node_reduction_rate", "node_reduction_pct",
    ],
}

ONTOLOGY_ALIASES = {
    "pairs_filtered": ["pairs_filtered", "merge_candidate_count", "pairs_to_merge"],
    "merged_pairs": ["merged_pairs", "actual_merged_pairs"],
    "cross_type_merge_rate": [
        "cross_type_merge_rate", "cross_category_merge_rate",
        "cross_class_merge_rate",
    ],
    "relation_preservation_rate": [
        "relation_preservation_rate", "relationship_preservation_rate",
    ],
}

SENSITIVITY_ALIASES = {
    "node_count_diff": ["node_count_diff", "node_diff"],
    "rel_count_diff": ["rel_count_diff", "relation_count_diff", "edge_count_diff"],
    "wcc_count_diff": ["wcc_count_diff", "wcc_diff"],
    "avg_degree_diff": ["avg_degree_diff", "average_degree_diff"],
    "modularity_diff": [
        "modularity_diff", "leiden_modularity_diff",
        "leiden_modularity_gamma1_diff",
    ],
    "node_reduction_ratio_diff": [
        "node_reduction_ratio_diff", "node_reduction_rate_diff",
    ],
}


# ─── 資料載入 ──────────────────────────────────────────────────────────────────

def load_summary(path: Path) -> dict:
    """讀取 matchgpt_3layer_summary.json（Phase 1 步驟 1.4.4 產出）"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_decisions(path: Path) -> list[dict]:
    """讀取 matchgpt_decisions.csv（Phase 1 步驟 1.4.2 產出）"""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def threshold_key(value) -> str:
    """將 0.7 / '0.7' / 't0.7' 正規化為 't0.7'。"""
    if value in (None, ""):
        return "N/A"
    text = str(value).strip()
    if text.startswith("t"):
        text = text[1:]
    try:
        num = float(text)
        return f"t{num:g}"
    except ValueError:
        return f"t{text}"


def threshold_number(tkey: str) -> float:
    try:
        return float(str(tkey).lstrip("t"))
    except ValueError:
        return float("inf")


def first_present(src: dict, aliases: list[str], default="N/A"):
    for key in aliases:
        if key in src and src[key] is not None:
            return src[key]
    return default


def ratio_pct(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value * 100:.2f}%"
    return str(value)


def get_thresholds(summary: dict) -> list[str]:
    if isinstance(summary.get("thresholds"), list) and summary["thresholds"]:
        return sorted(
            [threshold_key(t) for t in summary["thresholds"]],
            key=threshold_number,
        )

    keys = set()
    for section_name in (
        "structural", "ontology_consistency", "sensitivity",
        "layer1_structural", "layer2_ontology_consistency",
        "layer3_parameter_sensitivity",
    ):
        section = summary.get(section_name)
        if isinstance(section, dict):
            for key, row in section.items():
                if "_vs_" in str(key):
                    for part in str(key).split("_vs_"):
                        keys.add(threshold_key(part))
                elif isinstance(row, dict):
                    keys.add(threshold_key(row.get("threshold", key)))
        elif isinstance(section, list):
            for row in section:
                if isinstance(row, dict) and "threshold" in row:
                    keys.add(threshold_key(row["threshold"]))

    return sorted(keys, key=threshold_number) if keys else DEFAULT_THRESHOLDS


def section_by_threshold(summary: dict, primary: str, legacy: str, thresholds: list[str]) -> dict:
    """支援 list 與 dict 兩種 summary section 形式，輸出 {t0.7: row}。"""
    section = summary.get(primary)
    if section is None:
        section = summary.get(legacy, {})

    rows = {}
    if isinstance(section, dict):
        for key, row in section.items():
            if isinstance(row, dict):
                rows[threshold_key(row.get("threshold", key))] = row
    elif isinstance(section, list):
        for i, row in enumerate(section):
            if not isinstance(row, dict):
                continue
            raw_t = row.get("threshold")
            if raw_t is None and i < len(thresholds):
                raw_t = thresholds[i]
            rows[threshold_key(raw_t)] = row
    return rows


# ─── 計算 ──────────────────────────────────────────────────────────────────────

def compute_decision_stats(decisions: list[dict], thresholds: list[str]) -> dict:
    """
    從 matchgpt_decisions.csv 補充各 threshold 下的候選對統計。
    matchgpt_3layer_summary.json 的 pairs_filtered 記錄「送合併對數」，
    此處另算「total_candidate_pairs」（所有判定記錄，含 different）。
    """
    total = len(decisions)
    stats = {}
    for t in thresholds:
        t_float = threshold_number(t)
        same_above = sum(
            1 for d in decisions
            if d.get("decision") == "same"
            and _safe_float(d.get("confidence", 0)) >= t_float
        )
        stats[t] = {
            "total_candidate_pairs": total,
            "same_above_threshold":  same_above,
        }
    return stats


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─── 三層資料提取 ───────────────────────────────────────────────────────────────

def build_layer1(summary: dict, thresholds: list[str]) -> list[dict]:
    structural = section_by_threshold(summary, "structural", "layer1_structural", thresholds)
    rows = []
    for t in thresholds:
        m = structural.get(t, {})
        nr = first_present(m, STRUCTURAL_ALIASES["node_reduction_ratio"])
        rel_count = first_present(m, STRUCTURAL_ALIASES["rel_count"])
        rows.append({
            "threshold":            t,
            "node_count":           first_present(m, STRUCTURAL_ALIASES["node_count"]),
            "rel_count":            rel_count,
            "relation_count":       rel_count,
            "wcc_count":            first_present(m, STRUCTURAL_ALIASES["wcc_count"]),
            "avg_degree":           first_present(m, STRUCTURAL_ALIASES["avg_degree"]),
            "leiden_modularity":    first_present(m, STRUCTURAL_ALIASES["leiden_modularity"]),
            "node_reduction_ratio": nr,
            "node_reduction_ratio_pct": ratio_pct(nr),
        })
    return rows


def build_layer2(summary: dict, decision_stats: dict, thresholds: list[str]) -> list[dict]:
    ontology = section_by_threshold(
        summary, "ontology_consistency", "layer2_ontology_consistency", thresholds
    )
    rows = []
    for t in thresholds:
        m  = ontology.get(t, {})
        ds = decision_stats.get(t, {})
        ctr = first_present(m, ONTOLOGY_ALIASES["cross_type_merge_rate"])
        rpr = first_present(m, ONTOLOGY_ALIASES["relation_preservation_rate"])
        rows.append({
            "threshold":                  t,
            "total_candidate_pairs":      ds.get("total_candidate_pairs",
                                                  first_present(m, ONTOLOGY_ALIASES["pairs_filtered"])),
            "pairs_filtered":             first_present(m, ONTOLOGY_ALIASES["pairs_filtered"]),
            "merged_pairs":               first_present(m, ONTOLOGY_ALIASES["merged_pairs"]),
            "cross_type_merge_rate":      ctr,
            "cross_category_merge_rate":  ctr,
            "cross_type_merge_rate_pct":  ratio_pct(ctr),
            "cross_category_merge_rate_pct": ratio_pct(ctr),
            "relation_preservation_rate": rpr,
            "relation_preservation_rate_pct": ratio_pct(rpr),
        })
    return rows


def _diff(before, after):
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return round(after - before, 6)
    return "N/A"


def _normalize_sensitivity_row(label: str, m: dict) -> dict:
    return {
        "comparison":                 label,
        "node_count_diff":            first_present(m, SENSITIVITY_ALIASES["node_count_diff"]),
        "rel_count_diff":             first_present(m, SENSITIVITY_ALIASES["rel_count_diff"]),
        "wcc_count_diff":             first_present(m, SENSITIVITY_ALIASES["wcc_count_diff"]),
        "avg_degree_diff":            first_present(m, SENSITIVITY_ALIASES["avg_degree_diff"]),
        "modularity_diff":            first_present(m, SENSITIVITY_ALIASES["modularity_diff"]),
        "node_reduction_ratio_diff":  first_present(m, SENSITIVITY_ALIASES["node_reduction_ratio_diff"]),
    }


def build_layer3(summary: dict, thresholds: list[str], structural_rows: list[dict]) -> list[dict]:
    existing = summary.get("sensitivity")
    if existing is None:
        existing = summary.get("layer3_parameter_sensitivity", {})

    by_comparison = {}
    if isinstance(existing, dict):
        for label, m in existing.items():
            if isinstance(m, dict):
                by_comparison[label] = _normalize_sensitivity_row(label, m)
    elif isinstance(existing, list):
        for m in existing:
            if isinstance(m, dict):
                label = m.get("comparison")
                if label:
                    by_comparison[label] = _normalize_sensitivity_row(label, m)

    rows_by_t = {r["threshold"]: r for r in structural_rows}
    for left, right in combinations(thresholds, 2):
        label = f"{left}_vs_{right}"
        if left not in rows_by_t or right not in rows_by_t:
            continue
        before = rows_by_t[left]
        after = rows_by_t[right]
        computed = {
            "comparison":                label,
            "node_count_diff":           _diff(before["node_count"], after["node_count"]),
            "rel_count_diff":            _diff(before["rel_count"], after["rel_count"]),
            "wcc_count_diff":            _diff(before["wcc_count"], after["wcc_count"]),
            "avg_degree_diff":           _diff(before["avg_degree"], after["avg_degree"]),
            "modularity_diff":           _diff(before["leiden_modularity"], after["leiden_modularity"]),
            "node_reduction_ratio_diff": _diff(
                before["node_reduction_ratio"], after["node_reduction_ratio"]
            ),
        }
        existing_row = by_comparison.get(label, {})
        merged = {**computed, **{k: v for k, v in existing_row.items() if v != "N/A"}}
        by_comparison[label] = merged

    return [
        by_comparison[k]
        for k in sorted(
            by_comparison,
            key=lambda label: tuple(threshold_number(part) for part in label.split("_vs_")),
        )
    ]


# ─── Markdown 輸出 ─────────────────────────────────────────────────────────────

def to_markdown(data: dict) -> str:
    lines = [
        "## 表 4-7（指標二）：MatchGPT 進階節點整併三層指標",
        "",
        f"> 生成時間：{data['generated_at']}",
        "",
        "### 第一層：結構性指標",
        "",
        "| Threshold | 節點數 | 關係數 | WCC 數 | 平均節點度 | Leiden Modularity | 節點縮減比 |",
        "|-----------|--------|--------|--------|-----------|------------------|------------|",
    ]
    for r in data["layer1_structural"]:
        lines.append(
            f"| {r['threshold']} | {r['node_count']} | {r['rel_count']} "
            f"| {r['wcc_count']} | {r['avg_degree']} "
            f"| {r['leiden_modularity']} | {r['node_reduction_ratio_pct']} |"
        )

    lines += [
        "",
        "### 第二層：本體論一致性指標",
        "",
        "| Threshold | 候選對總數 | 送合併對數 | 實際合併對數 | 跨類別合併率 | 關係保留率 |",
        "|-----------|-----------|-----------|------------|------------|------------|",
    ]
    for r in data["layer2_ontology_consistency"]:
        lines.append(
            f"| {r['threshold']} | {r['total_candidate_pairs']} "
            f"| {r['pairs_filtered']} | {r['merged_pairs']} "
            f"| {r['cross_type_merge_rate_pct']} | {r['relation_preservation_rate_pct']} |"
        )

    lines += [
        "",
        "### 第三層：參數敏感性（相鄰 threshold 差值）",
        "",
        "| 比較組 | 節點數差值 | WCC 差值 | Modularity 差值 |",
        "|--------|-----------|---------|----------------|",
    ]
    for r in data["layer3_parameter_sensitivity"]:
        lines.append(
            f"| {r['comparison']} | {r['node_count_diff']} "
            f"| {r['wcc_count_diff']} | {r['modularity_diff']} |"
        )

    lines += ["", "---", ""]
    return "\n".join(lines)


# ─── 驗證 ──────────────────────────────────────────────────────────────────────

def validate_output(data: dict) -> list[str]:
    errors = []
    for key in (
        "generated_at", "threshold", "structural", "ontology_consistency",
        "sensitivity", "layer1_structural", "layer2_ontology_consistency",
        "layer3_parameter_sensitivity",
    ):
        if key not in data:
            errors.append(f"輸出 JSON 缺少 key: {key}")

    if len(data.get("threshold", [])) != 3:
        errors.append("threshold 應列出 3 個 threshold")
    if len(data.get("structural", [])) != 3:
        errors.append("structural 應有 3 個 threshold 列")
    if len(data.get("ontology_consistency", [])) != 3:
        errors.append("ontology_consistency 應有 3 個 threshold 列")
    if len(data.get("sensitivity", [])) < 1:
        errors.append("sensitivity 不應為空")
    if len(data.get("layer1_structural", [])) != 3:
        errors.append("layer1_structural 應有 3 個 threshold 列")
    if len(data.get("layer2_ontology_consistency", [])) != 3:
        errors.append("layer2_ontology_consistency 應有 3 個 threshold 列")
    if len(data.get("layer3_parameter_sensitivity", [])) < 1:
        errors.append("layer3_parameter_sensitivity 不應為空")

    return errors


# ─── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="實驗 8.1 指標二：MatchGPT 三層自動指標"
    )
    parser.add_argument("--summary",   required=True,
                        help="matchgpt_3layer_summary.json 路徑")
    parser.add_argument("--decisions", required=True,
                        help="matchgpt_decisions.csv 路徑")
    parser.add_argument("--output",    required=True,
                        help="輸出 JSON 路徑（同目錄下同名 .md 一併產出）")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary    = load_summary(Path(args.summary))
    decisions  = load_decisions(Path(args.decisions))
    thresholds = get_thresholds(summary)

    dec_stats = compute_decision_stats(decisions, thresholds)
    layer1    = build_layer1(summary, thresholds)
    layer2    = build_layer2(summary, dec_stats, thresholds)
    layer3    = build_layer3(summary, thresholds, layer1)

    output_data = {
        "generated_at":               datetime.now().isoformat(),
        "source_summary":             str(args.summary),
        "source_decisions":           str(args.decisions),
        "threshold":                  thresholds,
        "structural":                 layer1,
        "ontology_consistency":       layer2,
        "sensitivity":                layer3,
        "total_candidate_pairs":      dec_stats.get(thresholds[0], {}).get("total_candidate_pairs", "N/A"),
        "layer1_structural":          layer1,
        "layer2_ontology_consistency": layer2,
        "layer3_parameter_sensitivity": layer3,
    }

    errors = validate_output(output_data)
    if errors:
        print("[WARN] 驗證警告：")
        for e in errors:
            print(f"  - {e}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON     → {out_path}")

    md_path = out_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(output_data))
    print(f"✓ Markdown → {md_path}")


if __name__ == "__main__":
    main()
