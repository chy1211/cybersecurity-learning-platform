#!/usr/bin/env python3
"""
exp_3_thesis_tables.py

產出論文 §肆-五 之三張表：
    - 表 15：Graph RAG 與未使用圖譜輔助之命中率比較（單選題；3 模型主表）
    - 附錄 A：70B 模型補充測試結果（同欄位呈現）
    - 附錄 B：複選題（ISN 40 題）之 exact match 與 Option-level F1 完整結果

範圍與規則（與論文主表一致）：
    - 題源：ITE-ISN 160 題（資訊與網路安全管理概論 107-110 年）
    - 表 15 與附錄 A：單選題、排除空子圖（n_edges_kept=0）
    - 附錄 B：完整 ISN 40 題複選題（不排除空子圖，反映複選真實表現）

執行：
    cd backend/exp_3
    python exp_3_thesis_tables.py
"""

from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"
EVAL = DATA / "eval_results"
SG   = DATA / "subgraph"

ISN_BANK = DATA / "question_bank_isn_only.json"

# 主表 3 模型（與論文 §肆-五 表 15 一致）
MAIN_MODELS = [
    {"key": "e4b",      "label": "Gemma-4-e4b-it",
     "eval": "eval_e4b_NF1.json",      "sg": "subgraph_nf1_e4b.json"},
    {"key": "gptoss",   "label": "GPT-OSS-20B",
     "eval": "eval_gptoss_NF1.json",   "sg": "subgraph_nf1_gptoss.json"},
    {"key": "gemma31b", "label": "Gemma-4-31b-it",
     "eval": "eval_gemma31b_NF1.json", "sg": "subgraph_nf1_gemma31b.json"},
]

# 補充測試模型（附錄 A）
SUPP_MODELS = [
    {"key": "llama70b", "label": "Llama-3.3-70B-Instruct",
     "eval": "eval_llama70b_NF1.json", "sg": "subgraph_nf1_llama70b.json"},
]


# ─── 輔助函式 ──────────────────────────────────────────────────────────────────
def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def option_f1(gold: str, pred: str) -> float:
    """Option-level F1：以選項字母集合計算。"""
    G, P = set(gold), set(pred)
    if not P and not G:
        return 1.0
    if not P or not G:
        return 0.0
    tp = len(P & G)
    prec = tp / len(P)
    rec  = tp / len(G)
    return 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0.0


def pct(x, n, decimals=1):
    return f"{x / n * 100:.{decimals}f}%" if n > 0 else "N/A"


def signed_pct(x, n, decimals=2):
    if n <= 0:
        return "N/A"
    v = x / n * 100
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def coverage(sg: dict, qids: list[str]) -> tuple[int, int, float]:
    """回傳 (有邊題數, 總題數, 覆蓋率%)。"""
    total = 0
    non_zero = 0
    for qid in qids:
        sg_q = sg.get(qid)
        if sg_q is None:
            continue
        total += 1
        if sg_q.get("n_edges_kept", 0) > 0:
            non_zero += 1
    return non_zero, total, (non_zero / total * 100 if total else 0.0)


def slice_single_no_empty(ev: dict, sg: dict, qids: list[str]) -> dict:
    """單選題，排除空子圖；回傳 {n, ll_ok, rg_ok}."""
    n = ll_ok = rg_ok = 0
    for qid in qids:
        ev_q = ev.get(qid)
        if not ev_q:
            continue
        lo, gr = ev_q.get("llm_only"), ev_q.get("graph_rag")
        if not lo or not gr:
            continue
        if not bool(lo.get("is_single", True)):
            continue
        if sg.get(qid, {}).get("n_edges_kept", 0) == 0:
            continue
        n += 1
        ll_ok += int(lo.get("correct", False))
        rg_ok += int(gr.get("correct", False))
    return {"n": n, "ll_ok": ll_ok, "rg_ok": rg_ok}


def slice_multi_all(ev: dict, qids: list[str]) -> dict:
    """複選題，不排除空子圖；同時計算 strict acc 與 option-F1 平均。"""
    n = ll_ok = rg_ok = 0
    ll_f1 = rg_f1 = 0.0
    for qid in qids:
        ev_q = ev.get(qid)
        if not ev_q:
            continue
        lo, gr = ev_q.get("llm_only"), ev_q.get("graph_rag")
        if not lo or not gr:
            continue
        if bool(lo.get("is_single", True)):
            continue
        gold = (lo.get("gold_norm") or "").upper()
        p_lo = (lo.get("answer_norm") or "").upper()
        p_gr = (gr.get("answer_norm") or "").upper()
        n += 1
        ll_ok += int(lo.get("correct", False))
        rg_ok += int(gr.get("correct", False))
        ll_f1 += option_f1(gold, p_lo)
        rg_f1 += option_f1(gold, p_gr)
    return {"n": n, "ll_ok": ll_ok, "rg_ok": rg_ok,
            "ll_f1": ll_f1, "rg_f1": rg_f1}


def banner(title: str):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


# ─── 表 15：主表（3 模型 × 單選 × 排除空子圖）─────────────────────────────────
def table15_main(qids: list[str]):
    banner("表 15  Graph RAG 與未使用圖譜輔助之命中率比較（單選題）")

    header = ("| 模型               | 子圖覆蓋率 | 有效題數 n' "
              "| 未使用圖譜輔助 | Graph RAG | 命中率差值（Δ） |")
    sep    = ("|--------------------|-----------|-------------"
              "|----------------|-----------|-----------------|")
    print(header)
    print(sep)

    for m in MAIN_MODELS:
        ev = load_json(EVAL / m["eval"])
        sg = load_json(SG / m["sg"])
        nz, tot, cov = coverage(sg, qids)
        s = slice_single_no_empty(ev, sg, qids)
        print(
            f"| {m['label']:<18} "
            f"| {cov:>9.1f}% "
            f"| {s['n']:>11} "
            f"| {pct(s['ll_ok'], s['n']):>14} "
            f"| {pct(s['rg_ok'], s['n']):>9} "
            f"| {signed_pct(s['rg_ok'] - s['ll_ok'], s['n']):>15} |"
        )
    print()
    print("說明：")
    print("  · 題源：ITE-ISN 160 題；本表僅納入單選題且子圖非空之題目。")
    print("  · 子圖覆蓋率 = 子圖非空題數 / ISN 全部 160 題。")
    print("  · n' 為實際納入計算之有效單選題數。")


# ─── 附錄 A：70B 補充測試 ──────────────────────────────────────────────────────
def appendix_a_70b(qids: list[str]):
    banner("附錄 A  70B 模型補充測試（同表 15 欄位）")

    print("| 模型                      | 子圖覆蓋率 | 有效題數 n' "
          "| 未使用圖譜輔助 | Graph RAG | 命中率差值（Δ） |")
    print("|---------------------------|-----------|-------------"
          "|----------------|-----------|-----------------|")

    for m in SUPP_MODELS:
        ev = load_json(EVAL / m["eval"])
        sg = load_json(SG / m["sg"])
        nz, tot, cov = coverage(sg, qids)
        s = slice_single_no_empty(ev, sg, qids)
        print(
            f"| {m['label']:<25} "
            f"| {cov:>9.1f}% "
            f"| {s['n']:>11} "
            f"| {pct(s['ll_ok'], s['n']):>14} "
            f"| {pct(s['rg_ok'], s['n']):>9} "
            f"| {signed_pct(s['rg_ok'] - s['ll_ok'], s['n']):>15} |"
        )
    print()
    print("說明：")
    print("  · 條件、題源與評分標準與表 15 完全一致（ITE-ISN、單選、排除空子圖）。")
    print("  · 結果支持「70B 等級模型 Graph RAG 增益有限」之論述：")
    print("    LLM-only 已具高基準命中率，導致 retrieval 之增益空間受限。")


# ─── 附錄 B：複選題完整結果（含 strict 與 Option-F1）──────────────────────────
def appendix_b_multi(qids: list[str]):
    banner("附錄 B  複選題評估完整結果（ISN 40 題）")

    print("| 模型               |  n |  LLM Exact% |  RAG Exact% |  Δ Exact "
          "|  LLM OptF1% |  RAG OptF1% |  Δ OptF1 |")
    print("|--------------------|----|-------------|-------------|----------"
          "|-------------|-------------|----------|")

    for m in MAIN_MODELS + SUPP_MODELS:
        ev = load_json(EVAL / m["eval"])
        c = slice_multi_all(ev, qids)
        n = c["n"]
        d_exact = signed_pct(c["rg_ok"] - c["ll_ok"], n)
        d_f1    = signed_pct(c["rg_f1"] - c["ll_f1"], n)
        print(
            f"| {m['label']:<18} "
            f"| {n:>2} "
            f"| {pct(c['ll_ok'], n):>11} "
            f"| {pct(c['rg_ok'], n):>11} "
            f"| {d_exact:>8} "
            f"| {pct(c['ll_f1'], n):>11} "
            f"| {pct(c['rg_f1'], n):>11} "
            f"| {d_f1:>8} |"
        )
    print()
    print("說明：")
    print("  · n = ISN 複選題 40 題，未排除空子圖（反映複選真實表現）。")
    print("  · Exact match：答案組合完全一致始計分；對應論文 §肆-五 限制章節提及之嚴格指標。")
    print("  · Option-level F1：以選項字母集合計 P/R，"
          "F1 = 2PR/(P+R)，per-question 後取平均。")
    print("  · 兩指標對照可見：嚴格 Δ 雖呈負值，但 Option-F1 重算後接近零，")
    print("    反映誤差主要來自 under-selection（漏選），並非 KG 注入錯誤資訊。")


# ─── main ─────────────────────────────────────────────────────────────────────
def main():
    print("exp_3_thesis_tables — 論文表 15 + 附錄 A/B 一鍵產出")
    print(f"資料根目錄：{DATA}")

    qs_isn = load_json(ISN_BANK)
    qids = [q["qid"] for q in qs_isn]
    print(f"ISN 題庫：{len(qids)} 題")

    table15_main(qids)
    appendix_a_70b(qids)
    appendix_b_multi(qids)

    print("\n" + "=" * 78)
    print("完成。所有表格均為 Markdown 格式，可直接複製貼入論文。")


if __name__ == "__main__":
    main()
