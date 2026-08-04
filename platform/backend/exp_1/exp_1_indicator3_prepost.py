#!/usr/bin/env python3
"""
實驗 8.1 指標三：四階段管線跑前跑後結構指標對比

讀取 Phase 1 產出的 pre/post stats JSON 與最佳 threshold MatchGPT 指標，
計算三欄對比（Pre-validation / Post-validation / Post-MatchGPT），
輸出 JSON + Markdown 表格。

輸入欄位對應（支援常見 alias）：
  pre/post stats → node_count,
                   rel_count 或 relation_count,
                   wcc_count,
                   avg_degree 或 average_degree,
                   isolated_ratio 或 isolated_node_ratio,
                   leiden_modularity_gamma1 或 leiden_modularity
  matchgpt metrics → post_merge 內同上；若無 isolated ratio，會由
                     isolated_node_count / node_count 計算
                             + merge_stats.node_reduction_ratio, threshold

用法：
  python exp_1_indicator3_prepost.py \\
    --pre_stats   path/to/pre_validation_stats.json \\
    --post_stats  path/to/post_validation_stats.json \\
    --matchgpt_final path/to/matchgpt_t07_metrics.json \\
    --output      路徑/indicator3_prepost_compare.json
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


# 指標定義：(json_key, 顯示標籤, 格式化字串)
METRICS_DEF = [
    ("node_count",               "節點數",                   ""),
    ("rel_count",                "關係數",                   ""),
    ("wcc_count",                "弱連通元件數 (WCC)",        ""),
    ("avg_degree",               "平均節點度",               ".4f"),
    ("isolated_ratio",           "孤立節點比例",              ".4f"),
    ("leiden_modularity_gamma1", "Leiden Modularity (γ=1)",  ".6f"),
]

FIELD_ALIASES = {
    "node_count": [
        "node_count", "nodes", "node_total",
    ],
    "rel_count": [
        "rel_count", "relation_count", "relationship_count", "edge_count",
    ],
    "wcc_count": [
        "wcc_count", "weak_connected_component_count",
        "weakly_connected_component_count", "weakly_connected_components",
    ],
    "avg_degree": [
        "avg_degree", "average_degree", "mean_degree",
    ],
    "isolated_ratio": [
        "isolated_ratio", "isolated_node_ratio", "isolated_nodes_ratio",
    ],
    "leiden_modularity_gamma1": [
        "leiden_modularity_gamma1", "leiden_modularity", "modularity",
    ],
}


# ─── 資料載入 ──────────────────────────────────────────────────────────────────

def first_present(src: dict, aliases: list[str], default="N/A"):
    for key in aliases:
        if key in src and src[key] is not None:
            return src[key]
    return default


def normalize_stats(raw: dict) -> dict:
    """將 Phase 1 可能出現的欄位名稱正規化成本腳本內部 key。"""
    data = {}
    for key, aliases in FIELD_ALIASES.items():
        data[key] = first_present(raw, aliases)

    if data["isolated_ratio"] == "N/A":
        node_count = data.get("node_count")
        isolated_count = first_present(
            raw,
            ["isolated_node_count", "isolated_nodes", "isolated_count"],
        )
        if isinstance(node_count, (int, float)) and node_count > 0 and isinstance(isolated_count, (int, float)):
            data["isolated_ratio"] = round(isolated_count / node_count, 4)

    return data


def load_stats(path: Path) -> dict:
    """讀取 pre/post_validation_stats.json（格式由 Phase 1 步驟 1.2/1.3 產出）"""
    with open(path, encoding="utf-8") as f:
        return normalize_stats(json.load(f))


def load_matchgpt_final(path: Path) -> dict:
    """
    讀取 matchgpt_t??_metrics.json（Phase 1 步驟 1.4 產出）。
    從 post_merge 層提取結構指標；isolated_ratio 由 isolated_node_count/node_count 計算。
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    pm = raw.get("post_merge") or raw.get("post_matchgpt") or raw.get("structural") or raw
    ms = raw.get("merge_stats", {})

    def _v(src, key):
        v = src.get(key)
        return "N/A" if v is None else v

    normalized = normalize_stats(pm)

    return {
        "node_count":               normalized["node_count"],
        "rel_count":                normalized["rel_count"],
        "wcc_count":                normalized["wcc_count"],
        "avg_degree":               normalized["avg_degree"],
        "isolated_ratio":           normalized["isolated_ratio"],
        "leiden_modularity_gamma1": normalized["leiden_modularity_gamma1"],
        # 附加資訊（不進比較表，但放在輸出 JSON 供參考）
        "threshold":                _v(raw, "threshold"),
        "node_reduction_ratio":     _v(ms,  "node_reduction_ratio"),
        "merged_pairs":             _v(ms,  "merged_pairs"),
    }


# ─── 計算 ──────────────────────────────────────────────────────────────────────

def pct_change(before, after):
    """回傳 (絕對差值, 百分比字串)。任一為 N/A/None 則回傳 ('N/A', 'N/A')。"""
    if before in ("N/A", None) or after in ("N/A", None):
        return "N/A", "N/A"
    try:
        diff = after - before
        if before == 0:
            pct_str = "0.00%" if diff == 0 else "N/A"
        else:
            pct = diff / before * 100
            sign = "+" if diff >= 0 else ""
            pct_str = f"{sign}{pct:.2f}%"
        return diff, pct_str
    except TypeError:
        return "N/A", "N/A"


def build_comparison(pre: dict, post: dict, mgpt: dict) -> dict:
    rows = []
    for key, label, fmt_spec in METRICS_DEF:
        pre_v  = pre.get(key,  "N/A")
        post_v = post.get(key, "N/A")
        mgpt_v = mgpt.get(key, "N/A")

        _, pct_12    = pct_change(pre_v,  post_v)
        _, pct_23    = pct_change(post_v, mgpt_v)
        _, pct_total = pct_change(pre_v,  mgpt_v)

        rows.append({
            "metric":              key,
            "label":               label,
            "fmt_spec":            fmt_spec,
            "pre_validation":      pre_v,
            "post_validation":     post_v,
            "post_matchgpt":       mgpt_v,
            "change_pre_to_post":  pct_12,
            "change_post_to_mgpt": pct_23,
            "change_total":        pct_total,
        })

    mgpt_threshold = mgpt.get("threshold", "N/A")
    return {
        "generated_at": datetime.now().isoformat(),
        "stages": {
            "pre_validation":  "pre_validation_stats.json",
            "post_validation": "post_validation_stats.json",
            "post_matchgpt":   f"matchgpt_t{str(mgpt_threshold).replace('.','')}_metrics.json",
        },
        "matchgpt_extra": {
            "threshold":            mgpt_threshold,
            "node_reduction_ratio": mgpt.get("node_reduction_ratio", "N/A"),
            "merged_pairs":         mgpt.get("merged_pairs", "N/A"),
        },
        "rows": rows,
    }


# ─── 格式化輸出 ─────────────────────────────────────────────────────────────────

def fmt_val(val, fmt_spec: str) -> str:
    if val in ("N/A", None):
        return "N/A"
    try:
        return format(val, fmt_spec) if fmt_spec else str(val)
    except (TypeError, ValueError):
        return str(val)


def to_markdown(data: dict) -> str:
    rows        = data["rows"]
    mgpt_extra  = data["matchgpt_extra"]
    threshold   = mgpt_extra.get("threshold", "N/A")
    nr_ratio    = mgpt_extra.get("node_reduction_ratio", "N/A")
    nr_str      = f"{nr_ratio*100:.2f}%" if isinstance(nr_ratio, float) else str(nr_ratio)
    merged      = mgpt_extra.get("merged_pairs", "N/A")

    lines = [
        "## 表 4-7（指標三）：四階段管線跑前跑後結構指標對比",
        "",
        f"> 生成時間：{data['generated_at']}  ",
        f"> Post-MatchGPT threshold = {threshold}，"
        f"節點縮減比 = {nr_str}，實際合併節點對 = {merged}",
        "",
        "| 指標 | Pre-validation | Post-validation | Post-MatchGPT | Pre→Post | Post→MatchGPT |",
        "|------|---------------|----------------|--------------|----------|---------------|",
    ]

    for r in rows:
        fmt = r["fmt_spec"]
        pre_s  = fmt_val(r["pre_validation"],  fmt)
        post_s = fmt_val(r["post_validation"], fmt)
        mgpt_s = fmt_val(r["post_matchgpt"],   fmt)
        lines.append(
            f"| {r['label']} | {pre_s} | {post_s} | {mgpt_s} "
            f"| {r['change_pre_to_post']} | {r['change_post_to_mgpt']} |"
        )

    lines += [
        "",
        "### 質性說明",
        "",
        "**Pre-validation → Post-validation（四階段驗證管線之效果）**",
        "",
        "（待補：描述哪些類型之非法關係被攔截，以及結構改善情形）",
        "",
        "**Post-validation → Post-MatchGPT（MatchGPT 進階整併之效果）**",
        "",
        "（待補：描述 MatchGPT 進一步消除之冗餘節點類型與語意等價案例）",
        "",
    ]
    return "\n".join(lines)


# ─── 驗證 ──────────────────────────────────────────────────────────────────────

def validate_output(data: dict) -> list[str]:
    """回傳錯誤訊息清單；空清單表示驗證通過。"""
    errors = []
    required_keys = {"generated_at", "stages", "rows", "matchgpt_extra"}
    for k in required_keys:
        if k not in data:
            errors.append(f"輸出 JSON 缺少 key: {k}")

    rows = data.get("rows", [])
    expected_metrics = {m[0] for m in METRICS_DEF}
    actual_metrics   = {r["metric"] for r in rows}
    missing = expected_metrics - actual_metrics
    if missing:
        errors.append(f"rows 缺少指標：{missing}")

    for r in rows:
        for col in ("pre_validation", "post_validation", "post_matchgpt"):
            if col not in r:
                errors.append(f"指標 {r.get('metric')} 缺少欄位 {col}")

    return errors


# ─── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="實驗 8.1 指標三：四階段管線跑前跑後結構對比"
    )
    parser.add_argument("--pre_stats",      required=True,
                        help="pre_validation_stats.json 路徑")
    parser.add_argument("--post_stats",     required=True,
                        help="post_validation_stats.json 路徑")
    parser.add_argument("--matchgpt_final", required=True,
                        help="matchgpt_t??_metrics.json（最佳 threshold）路徑")
    parser.add_argument("--output",         required=True,
                        help="輸出 JSON 路徑（同目錄下同名 .md 一併產出）")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pre  = load_stats(Path(args.pre_stats))
    post = load_stats(Path(args.post_stats))
    mgpt = load_matchgpt_final(Path(args.matchgpt_final))

    comparison = build_comparison(pre, post, mgpt)

    errors = validate_output(comparison)
    if errors:
        print("[WARN] 驗證警告：")
        for e in errors:
            print(f"  - {e}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON     → {out_path}")

    md_path = out_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(comparison))
    print(f"✓ Markdown → {md_path}")


if __name__ == "__main__":
    main()
