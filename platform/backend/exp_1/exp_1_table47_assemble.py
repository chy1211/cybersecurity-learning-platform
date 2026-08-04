#!/usr/bin/env python3
"""
實驗 8.1 表 4-7 整合腳本

整合指標二（MatchGPT 三層）與指標三（跑前跑後結構對比），
產出論文表 4-7 完整 Markdown 草稿。

用法：
  python exp_1_table47_assemble.py \\
    --indicator2 路徑/indicator2_matchgpt_metrics.json \\
    --indicator3 路徑/indicator3_prepost_compare.json \\
    --output     路徑/表4-7草稿.md
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── 輔助格式化 ─────────────────────────────────────────────────────────────────

def fmt_val(val, fmt_spec: str) -> str:
    if val in ("N/A", None):
        return "N/A"
    try:
        return format(val, fmt_spec) if fmt_spec else str(val)
    except (TypeError, ValueError):
        return str(val)


def _pct_str(v) -> str:
    """把 float 轉 xx.xx% 字串，其他直接 str()"""
    if isinstance(v, float):
        return f"{v*100:.2f}%"
    return str(v)


def _rows(data: dict, primary: str, legacy: str) -> list[dict]:
    rows = data.get(primary)
    if rows is None:
        rows = data.get(legacy, [])
    return rows


# ─── Markdown 組裝 ─────────────────────────────────────────────────────────────

def assemble_table47(ind2: dict, ind3: dict) -> str:
    now = datetime.now().isoformat()
    mgpt_extra = ind3.get("matchgpt_extra", {})
    threshold  = mgpt_extra.get("threshold", "N/A")
    nr_ratio   = mgpt_extra.get("node_reduction_ratio", "N/A")
    nr_str     = _pct_str(nr_ratio) if isinstance(nr_ratio, float) else str(nr_ratio)
    merged     = mgpt_extra.get("merged_pairs", "N/A")

    lines = [
        "# 表 4-7：圖譜品質驗證指標整合（實驗 8.1）",
        "",
        f"> 生成時間：{now}  ",
        f"> 資料來源：指標二（MatchGPT 三層）+ 指標三（跑前跑後結構對比）  ",
        f"> 最佳 threshold = {threshold}，節點縮減比 = {nr_str}，合併對數 = {merged}",
        "",
        "---",
        "",
        "## 一、跑前跑後結構指標三欄對比（指標三）",
        "",
        "| 指標 | Pre-validation | Post-validation | Post-MatchGPT | Pre→Post | Post→MatchGPT |",
        "|------|---------------|----------------|--------------|----------|---------------|",
    ]

    for r in ind3.get("rows", []):
        fmt = r.get("fmt_spec", "")
        pre_s  = fmt_val(r["pre_validation"],  fmt)
        post_s = fmt_val(r["post_validation"], fmt)
        mgpt_s = fmt_val(r["post_matchgpt"],   fmt)
        lines.append(
            f"| {r['label']} | {pre_s} | {post_s} | {mgpt_s} "
            f"| {r['change_pre_to_post']} | {r['change_post_to_mgpt']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 二、MatchGPT 三層指標（指標二）",
        "",
        "### 2-1 第一層：結構性指標",
        "",
        "| Threshold | 節點數 | 關係數 | WCC 數 | 平均節點度 | Leiden Modularity | 節點縮減比 |",
        "|-----------|--------|--------|--------|-----------|------------------|------------|",
    ]

    for r in _rows(ind2, "structural", "layer1_structural"):
        lines.append(
            f"| {r['threshold']} | {r['node_count']} | {r['rel_count']} "
            f"| {r['wcc_count']} | {r['avg_degree']} "
            f"| {r['leiden_modularity']} | {r['node_reduction_ratio_pct']} |"
        )

    lines += [
        "",
        "### 2-2 第二層：本體論一致性指標",
        "",
        "| Threshold | 候選對總數 | 送合併對數 | 實際合併對數 | 跨類別合併率 | 關係保留率 |",
        "|-----------|-----------|-----------|------------|------------|------------|",
    ]

    for r in _rows(ind2, "ontology_consistency", "layer2_ontology_consistency"):
        lines.append(
            f"| {r['threshold']} | {r['total_candidate_pairs']} "
            f"| {r['pairs_filtered']} | {r['merged_pairs']} "
            f"| {r['cross_type_merge_rate_pct']} | {r['relation_preservation_rate_pct']} |"
        )

    lines += [
        "",
        "### 2-3 第三層：參數敏感性",
        "",
        "| 比較組 | 節點數差值 | WCC 差值 | Modularity 差值 |",
        "|--------|-----------|---------|----------------|",
    ]

    for r in _rows(ind2, "sensitivity", "layer3_parameter_sensitivity"):
        lines.append(
            f"| {r['comparison']} | {r['node_count_diff']} "
            f"| {r['wcc_count_diff']} | {r['modularity_diff']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 三、質性說明（待補）",
        "",
        "### 3-1 Pre-validation → Post-validation",
        "",
        "（待補：描述哪些類型之非法關係被攔截，以及結構改善情形。"
        "參考：107 筆拒絕案例分布 — Step 3 語意 95 筆 / Phase 1c Schema Edge 11 筆 / Step 1 類別 1 筆）",
        "",
        "### 3-2 Post-validation → Post-MatchGPT",
        "",
        "（待補：MatchGPT 進一步消除之冗餘節點類型，典型合併案例 2–3 例）",
        "",
        "### 3-3 Threshold 選擇說明",
        "",
        "（待補：說明最佳 threshold 選擇邏輯 —— 跨類別合併率 = 0% 為硬性前提，"
        "次選結構性指標改善幅度最大者）",
        "",
        "---",
        "",
        "_此草稿由 exp_1_table47_assemble.py 自動生成，括號內文字需人工填寫後刪除。_",
        "",
    ]

    return "\n".join(lines)


# ─── 驗證 ──────────────────────────────────────────────────────────────────────

def validate_markdown(md: str) -> list[str]:
    errors = []
    required_sections = [
        "Pre-validation",
        "Post-validation",
        "Post-MatchGPT",
        "第一層",
        "第二層",
        "第三層",
    ]
    for s in required_sections:
        if s not in md:
            errors.append(f"Markdown 缺少段落標記：{s}")

    table_lines = [l for l in md.splitlines() if l.startswith("|")]
    if len(table_lines) < 3:
        errors.append("Markdown 表格行數不足")

    return errors


# ─── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="表 4-7 整合：指標二 + 指標三")
    parser.add_argument("--indicator2", required=True,
                        help="indicator2_matchgpt_metrics.json 路徑")
    parser.add_argument("--indicator3", required=True,
                        help="indicator3_prepost_compare.json 路徑")
    parser.add_argument("--output",     required=True,
                        help="輸出 Markdown 路徑")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ind2 = load_json(Path(args.indicator2))
    ind3 = load_json(Path(args.indicator3))

    md = assemble_table47(ind2, ind3)

    errors = validate_markdown(md)
    if errors:
        print("[WARN] Markdown 驗證警告：")
        for e in errors:
            print(f"  - {e}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ Markdown → {out_path}")


if __name__ == "__main__":
    main()
