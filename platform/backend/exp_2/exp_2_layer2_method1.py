#!/usr/bin/env python3
from __future__ import annotations

import os

# Load backend .env when this script is executed directly.
try:
    from pathlib import Path as _EnvPath
    from dotenv import load_dotenv as _load_dotenv
    for _env_parent in _EnvPath(__file__).resolve().parents:
        _env_file = _env_parent / ".env"
        if _env_file.exists():
            _load_dotenv(_env_file)
            break
except Exception:
    pass
"""Exp 2 Layer 2 Method 1: Ontology Attribute Enrichment Analysis

驗證 Leiden 拓樸社群是否與本體論 entity type 有非隨機的收斂性。

方法：
  1. Shannon entropy per community（描述統計）
     - 計算各社群的 entity type 分布熵，對比全圖背景熵
  2. Hypergeometric enrichment test + BH correction（正式推論）
     - 對每個 (community, entity_type) 組合計算富集顯著性
     - Benjamini-Hochberg FDR 校正，主要門檻 q < 0.05

社群範圍：size ≥ 10（36 個有效社群）
文獻依據：Halu et al. (2019) 以 ≥10 為有效社群門檻

資料來源：直接從 Neo4j 查詢（非從 pairs.csv 重建），確保母體 M 完整。

用法：
  python exp_2_layer2_method1.py                    # 真實模式
  python exp_2_layer2_method1.py --mock_neo4j       # 離線測試
"""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import hypergeom

# matplotlib 必須在 import pyplot 之前設定 backend
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# ─── 路徑常數 ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
BASE_DIR    = _HERE.parents[4]
RESULTS_DIR = BASE_DIR / "論文" / "實驗" / "實驗2_Leiden三層驗證" / "結果" / "layer2"

DEFAULT_OUTPUT_JSON    = RESULTS_DIR / "layer2_method1_enrichment.json"
DEFAULT_OUTPUT_HEATMAP = RESULTS_DIR / "layer2_method1_enrichment_heatmap.png"
DEFAULT_OUTPUT_MD      = RESULTS_DIR / "layer2_method1_summary.md"

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

MIN_COMMUNITY_SIZE  = 10
Q_THRESHOLD_PRIMARY = 0.05
Q_THRESHOLD_SUPP    = 0.10


# ─── Neo4j 查詢 ───────────────────────────────────────────────────────────────

def fetch_nodes_from_neo4j(uri: str, user: str, password: str) -> list[dict]:
    """從 Neo4j 取得所有有 communityId 的節點（直接查全圖，保證 M 完整）。"""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError(
            "neo4j package 未安裝，請 pip install neo4j 或使用 --mock_neo4j"
        ) from exc

    query = """
    MATCH (n:KGNode)
    WHERE n.communityId IS NOT NULL
    RETURN n.communityId AS community_id,
           n.type        AS entity_type,
           coalesce(n.name, n.id) AS name
    """
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            rows = [dict(r) for r in session.run(query)]
    finally:
        driver.close()
    return rows


def build_mock_nodes() -> list[dict]:
    """8 個模擬社群（每個 ≥ 10 節點），entity type 分布差異明顯，用於離線測試。"""
    type_distributions = [
        (0,  [("policy", 8), ("tool", 4), ("attack", 1)]),
        (1,  [("attack", 9), ("technique", 3), ("tool", 1)]),
        (2,  [("tool", 10), ("policy", 2), ("risk", 1)]),
        (3,  [("risk", 8),  ("policy", 4), ("tool", 1)]),
        (4,  [("technique", 9), ("tool", 3), ("attack", 1)]),
        (5,  [("policy", 7), ("risk", 5), ("tool", 1)]),
        (6,  [("attack", 8), ("tool", 4), ("technique", 1)]),
        (7,  [("tool", 9), ("technique", 3), ("policy", 1)]),
    ]
    nodes = []
    for cid, type_dist in type_distributions:
        for typ, count in type_dist:
            for i in range(count):
                nodes.append({
                    "community_id": str(cid),
                    "entity_type":  typ,
                    "name":         f"mock_{cid}_{typ}_{i}",
                })
    return nodes


# ─── 工具函式 ──────────────────────────────────────────────────────────────────

def normalize_community_id(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    s = str(value)
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s.strip()


def cid_sort_key(cid: str) -> tuple[int, Any]:
    try:
        return (0, int(cid))
    except ValueError:
        return (1, cid)


def calc_entropy(type_counts: "pd.Series") -> float:
    total = type_counts.sum()
    if total == 0:
        return 0.0
    probs = type_counts / total
    return float(-sum(p * math.log2(p) for p in probs if p > 0))


def bh_correction(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR step-down correction。回傳與輸入等長的校正後 q 值清單。"""
    n = len(pvals)
    if n == 0:
        return []
    order    = sorted(range(n), key=lambda i: pvals[i])   # 升冪排列的原始索引
    adjusted = [1.0] * n
    prev     = 1.0
    for rank_i in range(n - 1, -1, -1):                   # 從最大 rank 往下掃
        rank     = rank_i + 1                              # 1-indexed
        orig_idx = order[rank_i]
        adj      = pvals[orig_idx] * n / rank
        adj      = min(adj, prev, 1.0)
        adjusted[orig_idx] = adj
        prev = adj
    return adjusted


# ─── 主分析邏輯 ───────────────────────────────────────────────────────────────

def run_analysis(nodes: list[dict], min_size: int = MIN_COMMUNITY_SIZE) -> dict:
    df = pd.DataFrame(nodes)
    df["community_id"] = df["community_id"].apply(normalize_community_id)
    df = df[df["community_id"] != "UNKNOWN"].copy()
    df["entity_type"] = df["entity_type"].fillna("Unknown").astype(str)
    df["entity_type"] = df["entity_type"].replace("", "Unknown")

    # ── 篩選 size ≥ min_size 的社群 ──────────────────────────────────────────
    comm_sizes    = df.groupby("community_id").size()
    eligible_cids = sorted(
        [c for c, s in comm_sizes.items() if s >= min_size],
        key=cid_sort_key,
    )
    df_eligible = df[df["community_id"].isin(eligible_cids)].copy()

    print(f"  全圖節點數（有 communityId）：{len(df)}")
    print(f"  ≥{min_size} 節點社群數：{len(eligible_cids)}")
    print(f"  納入分析節點數：{len(df_eligible)}")

    # Cross-tabulation: rows=community, cols=entity_type
    comm_type  = df_eligible.groupby(["community_id", "entity_type"]).size().unstack(fill_value=0)
    communities = [c for c in eligible_cids if c in comm_type.index]
    comm_type   = comm_type.loc[communities]   # 確保排序一致
    types       = sorted(comm_type.columns.tolist())
    comm_type   = comm_type[types]

    # ─── 1. Shannon Entropy（描述統計）────────────────────────────────────────
    entropies      = {cid: calc_entropy(comm_type.loc[cid]) for cid in communities}
    global_counts  = df_eligible["entity_type"].value_counts()
    global_entropy = calc_entropy(global_counts)

    mean_entropy   = float(np.mean(list(entropies.values())))
    median_entropy = float(np.median(list(entropies.values())))
    below_global   = sum(1 for e in entropies.values() if e < global_entropy)

    print(f"\n[Shannon Entropy]")
    print(f"  全圖背景 entropy：{global_entropy:.4f}")
    print(f"  社群 entropy 平均：{mean_entropy:.4f}，中位：{median_entropy:.4f}")
    print(f"  entropy < 全圖背景的社群數：{below_global} / {len(communities)}")

    # ─── 2. Hypergeometric Enrichment + BH ────────────────────────────────────
    M                      = len(df_eligible)
    global_type_counts_dict = dict(global_counts)

    records = []
    for cid in communities:
        N = int(comm_type.loc[cid].sum())
        for t in types:
            k = int(comm_type.loc[cid, t])
            n = int(global_type_counts_dict.get(t, 0))
            p_val = float(hypergeom.sf(k - 1, M, n, N)) if k > 0 else 1.0
            records.append({
                "community_id": cid,
                "entity_type":  t,
                "k": k, "N": N, "n": n, "M": M,
                "p_value": p_val,
            })

    pvals    = [r["p_value"] for r in records]
    adj      = bh_correction(pvals)
    for i, rec in enumerate(records):
        rec["q_value"] = adj[i]

    sig_q05        = sum(1 for r in records if r["q_value"] < Q_THRESHOLD_PRIMARY)
    sig_q10        = sum(1 for r in records if r["q_value"] < Q_THRESHOLD_SUPP)
    sig_comms_q05  = len({r["community_id"] for r in records if r["q_value"] < Q_THRESHOLD_PRIMARY})
    sig_comms_q10  = len({r["community_id"] for r in records if r["q_value"] < Q_THRESHOLD_SUPP})

    print(f"\n[Hypergeometric Enrichment — BH 校正]")
    print(f"  多重比較次數：{len(records)}（{len(communities)} 社群 × {len(types)} 類型）")
    print(f"  顯著 (community, type) 對：q<0.05 → {sig_q05}；q<0.10 → {sig_q10}")
    print(f"  涉及社群數：q<0.05 → {sig_comms_q05}；q<0.10 → {sig_comms_q10}")

    enrichment_table = [
        {
            "community_id":    r["community_id"],
            "entity_type":     r["entity_type"],
            "k":               r["k"],
            "N":               r["N"],
            "n":               r["n"],
            "M":               r["M"],
            "p_value":         round(r["p_value"], 8),
            "q_value":         round(r["q_value"], 8),
            "significant_q05": r["q_value"] < Q_THRESHOLD_PRIMARY,
            "significant_q10": r["q_value"] < Q_THRESHOLD_SUPP,
        }
        for r in records
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "layer":  "semantic",
        "method": "ontology_attribute_enrichment",
        "parameters": {
            "min_community_size":         min_size,
            "q_threshold_primary":        Q_THRESHOLD_PRIMARY,
            "q_threshold_supplementary":  Q_THRESHOLD_SUPP,
            "n_communities":              len(communities),
            "n_entity_types":             len(types),
            "n_comparisons":              len(records),
            "total_nodes_M":              M,
        },
        "entropy_summary": {
            "global_entropy":           round(global_entropy, 4),
            "mean_community_entropy":   round(mean_entropy, 4),
            "median_community_entropy": round(median_entropy, 4),
            "communities_below_global": below_global,
            "total_communities":        len(communities),
            "per_community": {cid: round(e, 4) for cid, e in entropies.items()},
        },
        "enrichment_summary": {
            "sig_pairs_q05":      sig_q05,
            "sig_pairs_q10":      sig_q10,
            "sig_communities_q05": sig_comms_q05,
            "sig_communities_q10": sig_comms_q10,
        },
        "enrichment_table": enrichment_table,
        "communities":  communities,
        "entity_types": types,
    }


# ─── 視覺化 ───────────────────────────────────────────────────────────────────

def plot_heatmap(results: dict, output_path: Path) -> None:
    communities = results["communities"]
    types       = results["entity_types"]
    table       = results["enrichment_table"]

    q_matrix = pd.DataFrame(1.0, index=communities, columns=types, dtype=float)
    for rec in table:
        cid = rec["community_id"]
        t   = rec["entity_type"]
        if cid in q_matrix.index and t in q_matrix.columns:
            q_matrix.loc[cid, t] = rec["q_value"]

    log_q = -np.log10(np.clip(q_matrix.values.astype(float), 1e-10, 1.0))
    log_q_df = pd.DataFrame(log_q, index=communities, columns=types)

    plt.rcParams["font.sans-serif"] = [
        "Microsoft JhengHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig_h = max(8, len(communities) * 0.38)
    fig_w = max(10, len(types) * 1.1)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    sns.heatmap(
        log_q_df,
        cmap="YlOrRd",
        annot=False,
        linewidths=0.3,
        linecolor="lightgray",
        cbar_kws={"label": "-log₁₀(q-value, BH-adjusted)"},
        ax=ax,
    )
    sig_line = -math.log10(Q_THRESHOLD_PRIMARY)
    ax.set_title(
        f"Community × Entity Type Enrichment\n"
        f"(-log₁₀ BH-adjusted q-value；虛線 = q<{Q_THRESHOLD_PRIMARY} 對應 {sig_line:.2f})",
        fontsize=12,
    )
    ax.set_xlabel("Entity Type", fontsize=10)
    ax.set_ylabel("Community ID", fontsize=10)
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.yticks(fontsize=7)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Heatmap → {output_path}")


# ─── Markdown 摘要 ─────────────────────────────────────────────────────────────

def write_markdown_summary(results: dict, output_path: Path) -> None:
    es = results["entropy_summary"]
    en = results["enrichment_summary"]
    p  = results["parameters"]

    lines = [
        "# Layer 2 Method 1：本體屬性富集分析摘要",
        "",
        f"**生成時間**：{results['generated_at']}",
        "",
        "## 分析範圍",
        f"- 社群最小節點數門檻：{p['min_community_size']}（依據 Halu et al., 2019）",
        f"- 有效社群數：{p['n_communities']}",
        f"- Entity type 種類：{p['n_entity_types']}",
        f"- 多重比較次數：{p['n_comparisons']}",
        f"- 母體節點數 (M)：{p['total_nodes_M']}",
        "",
        "## Shannon Entropy（描述統計）",
        f"- 全圖背景 entropy：**{es['global_entropy']}**",
        f"- 社群 entropy 平均：**{es['mean_community_entropy']}**",
        f"- 社群 entropy 中位：**{es['median_community_entropy']}**",
        f"- entropy 低於全圖背景的社群：{es['communities_below_global']} / {es['total_communities']}",
        "",
        "## Hypergeometric Enrichment + BH 校正（正式推論）",
        f"- 顯著 (community, type) 對（q < 0.05）：**{en['sig_pairs_q05']}**",
        f"- 涉及社群數（q < 0.05）：**{en['sig_communities_q05']} / {p['n_communities']}**",
        f"- 補充分析（q < 0.10）：{en['sig_pairs_q10']} 對，涉及 {en['sig_communities_q10']} 個社群",
        "",
        "## 論文引用語（草稿）",
        "",
        f"在 {p['n_communities']} 個有效社群（≥{p['min_community_size']} 節點）中，"
        f"共有 {en['sig_communities_q05']} 個社群呈現至少一種 entity type 的顯著富集"
        f"（Hypergeometric test，BH-adjusted q < {p['q_threshold_primary']}），"
        "佐證 Leiden 拓樸分群具有非隨機的本體論型別收斂性（Singh et al., 2023）。",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Markdown 摘要 → {output_path}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exp 2 Layer 2 Method 1: Ontology Attribute Enrichment"
    )
    parser.add_argument("--uri",      default=NEO4J_URI)
    parser.add_argument("--user",     default=NEO4J_USER)
    parser.add_argument("--password", default=NEO4J_PASSWORD)
    parser.add_argument("--min_size", type=int, default=MIN_COMMUNITY_SIZE,
                        help="社群最小節點數門檻（預設 10）")
    parser.add_argument("--output_json",    type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output_heatmap", type=Path, default=DEFAULT_OUTPUT_HEATMAP)
    parser.add_argument("--output_md",      type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--mock_neo4j", action="store_true",
                        help="使用 mock 節點離線測試（不連 Neo4j）")
    args = parser.parse_args()

    print("=" * 60)
    print("[Layer2-M1] 本體屬性富集分析")
    print(f"  模式：{'MOCK (離線)' if args.mock_neo4j else f'Neo4j ({args.uri})'}")
    print("=" * 60)

    if args.mock_neo4j:
        nodes = build_mock_nodes()
        print(f"  Mock 節點數：{len(nodes)}")
    else:
        nodes = fetch_nodes_from_neo4j(args.uri, args.user, args.password)
        print(f"  查詢節點數：{len(nodes)}")

    results = run_analysis(nodes, min_size=args.min_size)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  JSON → {args.output_json}")

    plot_heatmap(results, args.output_heatmap)
    write_markdown_summary(results, args.output_md)

    print("\n[Layer2-M1] 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
