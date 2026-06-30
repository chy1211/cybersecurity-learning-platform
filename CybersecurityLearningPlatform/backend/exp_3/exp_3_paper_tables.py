#!/usr/bin/env python3
"""
exp_3_paper_tables.py
產出 實驗 3 論文所需的所有表格（Markdown 格式）。

執行：
    cd backend/exp_3
    python exp_3_paper_tables.py
"""

from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"
EVAL = DATA / "eval_results"
SG   = DATA / "subgraph"

# ─── 模型設定 ──────────────────────────────────────────────────────────────────
NF1_MODELS = [
    {"key": "e4b",      "label": "Gemma-4-e4b-it",  "eval": "eval_e4b_NF1.json",      "sg": "subgraph_nf1_e4b.json"},
    {"key": "gptoss",   "label": "GPT-OSS-20B",      "eval": "eval_gptoss_NF1.json",   "sg": "subgraph_nf1_gptoss.json"},
    {"key": "gemma31b", "label": "Gemma-4-31b-it",   "eval": "eval_gemma31b_NF1.json", "sg": "subgraph_nf1_gemma31b.json"},
]

ISN_ONLY_BANK = DATA / "question_bank_isn_only.json"
FULL_BANK     = DATA / "question_bank_329.json"


# ─── 輔助函式 ──────────────────────────────────────────────────────────────────
def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def option_f1(gold: str, pred: str) -> float:
    G, P = set(gold), set(pred)
    if not P and not G:
        return 1.0
    if not P or not G:
        return 0.0
    tp = len(P & G)
    prec = tp / len(P)
    rec  = tp / len(G)
    return 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0.0


def pct(ok: int | float, n: int, decimals: int = 1) -> str:
    return f"{ok / n * 100:.{decimals}f}%" if n > 0 else "N/A"


def delta(ok_rag: int | float, ok_llm: int | float, n: int, decimals: int = 2) -> str:
    d = (ok_rag - ok_llm) / n * 100 if n > 0 else 0.0
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.{decimals}f}pp"


def calc_slice(ev: dict, sg: dict | None, qids: list[str], single_only: bool | None,
               exclude_empty: bool) -> dict:
    """
    回傳 {n, ll_ok, rg_ok, ll_f1, rg_f1} for strict and option-F1.
    single_only=True→單選, False→複選, None→全部.
    """
    n = ll_ok = rg_ok = 0
    ll_f1 = rg_f1 = 0.0
    for qid in qids:
        ev_q = ev.get(qid)
        if not ev_q:
            continue
        lo = ev_q.get("llm_only")
        gr = ev_q.get("graph_rag")
        if not lo or not gr:
            continue
        is_single = bool(lo.get("is_single", True))
        if single_only is True and not is_single:
            continue
        if single_only is False and is_single:
            continue
        if exclude_empty and sg:
            sg_q = sg.get(qid, {})
            if sg_q.get("n_edges_kept", 0) == 0:
                continue
        gold = (lo.get("gold_norm") or "").upper()
        p_lo = (lo.get("answer_norm") or "").upper()
        p_gr = (gr.get("answer_norm") or "").upper()
        n += 1
        ll_ok += int(lo.get("correct", False))
        rg_ok += int(gr.get("correct", False))
        ll_f1 += option_f1(gold, p_lo)
        rg_f1 += option_f1(gold, p_gr)
    return {"n": n, "ll_ok": ll_ok, "rg_ok": rg_ok, "ll_f1": ll_f1, "rg_f1": rg_f1}


def print_sep(title: str = "") -> None:
    print("\n" + "=" * 72)
    if title:
        print(f"  {title}")
        print("=" * 72)


# ─── Table 1：NF1 ISN 排除空子圖，單選 / 複選 / 全題（嚴格比對）────────────────
def table1_main_result():
    print_sep("Table 1  NF1 × ISN（排除空子圖）— 嚴格完全比對")
    qs_isn = load_json(ISN_ONLY_BANK)
    isn_ids = [q["qid"] for q in qs_isn]

    header = f"| {'模型':<18} | {'n':>4} | {'LLM單%':>8} | {'RAG單%':>8} | {'Δ單選':>9} " \
             f"| {'n':>4} | {'LLM複%':>8} | {'RAG複%':>8} | {'Δ複選':>9} " \
             f"| {'n全':>4} | {'LLM全%':>8} | {'RAG全%':>8} | {'Δ全題':>9} |"
    sep = "|" + "|".join(["-" * w for w in [20, 6, 10, 10, 11, 6, 10, 10, 11, 6, 10, 10, 11]]) + "|"
    print(header)
    print(sep)

    for m in NF1_MODELS:
        ev = load_json(EVAL / m["eval"])
        sg = load_json(SG / m["sg"])
        s = calc_slice(ev, sg, isn_ids, True,  exclude_empty=True)
        c = calc_slice(ev, sg, isn_ids, False, exclude_empty=True)
        a = calc_slice(ev, sg, isn_ids, None,  exclude_empty=True)
        print(
            f"| {m['label']:<18} "
            f"| {s['n']:>4} | {pct(s['ll_ok'], s['n']):>8} | {pct(s['rg_ok'], s['n']):>8} | {delta(s['rg_ok'], s['ll_ok'], s['n']):>9} "
            f"| {c['n']:>4} | {pct(c['ll_ok'], c['n']):>8} | {pct(c['rg_ok'], c['n']):>8} | {delta(c['rg_ok'], c['ll_ok'], c['n']):>9} "
            f"| {a['n']:>4} | {pct(a['ll_ok'], a['n']):>8} | {pct(a['rg_ok'], a['n']):>8} | {delta(a['rg_ok'], a['ll_ok'], a['n']):>9} |"
        )
    print()
    print("※ 空子圖（n_edges_kept=0）已排除；單選 n 約 109~118，複選 n 約 36~38")


# ─── Table 2：含空子圖版本（對照用）─────────────────────────────────────────────
def table2_with_empty():
    print_sep("Table 2  NF1 × ISN（含空子圖）— 完整 n=160（參考用）")
    qs_isn = load_json(ISN_ONLY_BANK)
    isn_ids = [q["qid"] for q in qs_isn]

    print(f"| {'模型':<18} | {'n':>4} | {'LLM單%':>8} | {'RAG單%':>8} | {'Δ單選':>9} "
          f"| {'n':>4} | {'LLM複%':>8} | {'RAG複%':>8} | {'Δ複選':>9} |")
    print("|" + "|".join(["-" * w for w in [20, 6, 10, 10, 11, 6, 10, 10, 11]]) + "|")

    for m in NF1_MODELS:
        ev = load_json(EVAL / m["eval"])
        sg = load_json(SG / m["sg"])
        s = calc_slice(ev, sg, isn_ids, True,  exclude_empty=False)
        c = calc_slice(ev, sg, isn_ids, False, exclude_empty=False)
        print(
            f"| {m['label']:<18} "
            f"| {s['n']:>4} | {pct(s['ll_ok'], s['n']):>8} | {pct(s['rg_ok'], s['n']):>8} | {delta(s['rg_ok'], s['ll_ok'], s['n']):>9} "
            f"| {c['n']:>4} | {pct(c['ll_ok'], c['n']):>8} | {pct(c['rg_ok'], c['n']):>8} | {delta(c['rg_ok'], c['ll_ok'], c['n']):>9} |"
        )


# ─── Table 3：複選題 Strict vs Option-F1 對比 ──────────────────────────────────
def table3_multi_scoring():
    print_sep("Table 3  複選題 Limitation — 嚴格比對 vs Option-level F1（ISN，排除空子圖）")
    qs_isn = load_json(ISN_ONLY_BANK)
    isn_ids = [q["qid"] for q in qs_isn]

    print(f"| {'模型':<18} | {'Δ嚴格':>9} | {'LLM_F1%':>9} | {'RAG_F1%':>9} | {'Δ_F1':>9} |")
    print("|" + "|".join(["-" * w for w in [20, 11, 11, 11, 11]]) + "|")

    for m in NF1_MODELS:
        ev = load_json(EVAL / m["eval"])
        sg = load_json(SG / m["sg"])
        c  = calc_slice(ev, sg, isn_ids, False, exclude_empty=True)
        n = c["n"]
        d_strict = delta(c["rg_ok"], c["ll_ok"], n)
        llm_f1   = pct(c["ll_f1"], n)
        rag_f1   = pct(c["rg_f1"], n)
        d_f1     = delta(c["rg_f1"], c["ll_f1"], n)
        print(f"| {m['label']:<18} | {d_strict:>9} | {llm_f1:>9} | {rag_f1:>9} | {d_f1:>9} |")

    print()
    print("※ Option-level F1 = 2×Precision×Recall / (Precision+Recall)，per question 後取平均")


# ─── Table 4：複選題錯誤模式分析（LLM-only）─────────────────────────────────────
def table4_error_pattern():
    print_sep("Table 4  複選題錯誤模式（LLM-only，ISN 160 題）")
    qs_isn = load_json(ISN_ONLY_BANK)
    multi_qs = [q for q in qs_isn if not q.get("is_single", True)]

    # 金標準分布
    gold_dist: dict[int, int] = {}
    for q in multi_qs:
        n = len(q["answer"].upper().replace(" ", "").translate(str.maketrans("", "", "ABCD".join(set("ABCD") - set(q["answer"].upper())))))
        # simpler: just count A-D chars
        g = "".join(c for c in q["answer"].upper() if c in "ABCD")
        gold_dist[len(g)] = gold_dist.get(len(g), 0) + 1

    print(f"金標準答案組合數分布：{dict(sorted(gold_dist.items()))}")
    print()
    print(f"| {'模型':<18} | {'正確':>4} | {'選太少':>6} | 其中退化單選 | {'選太多':>6} | {'等量選錯':>8} |")
    print("|" + "|".join(["-" * w for w in [20, 6, 8, 14, 8, 10]]) + "|")

    for m in NF1_MODELS:
        ev = load_json(EVAL / m["eval"])
        correct = under = under_single = over = wrong = 0
        for q in multi_qs:
            r = ev.get(q["qid"], {}).get("llm_only")
            if not r:
                continue
            gold = "".join(c for c in q["answer"].upper() if c in "ABCD")
            pred = "".join(c for c in (r.get("answer_norm") or "").upper() if c in "ABCD")
            if gold == pred:
                correct += 1
                continue
            gn, pn = len(gold), len(pred)
            if pn < gn:
                under += 1
                if pn == 1:
                    under_single += 1
            elif pn > gn:
                over += 1
            else:
                wrong += 1
        total = len(multi_qs)
        print(f"| {m['label']:<18} | {correct:>4} | {under:>6} | {under_single:>12} | {over:>6} | {wrong:>8} |")

    print()
    print(f"※ 複選題 n={len(multi_qs)}；under-select = 應選項目數 > 實際選項目數")


# ─── Table 5：Subgraph coverage 統計 ──────────────────────────────────────────
def table5_coverage():
    print_sep("Table 5  NF1 Subgraph Coverage（ISN 160 題）")
    qs_isn = load_json(ISN_ONLY_BANK)
    isn_ids = [q["qid"] for q in qs_isn]

    print(f"| {'模型':<18} | {'總題':>4} | {'有邊題數':>8} | {'覆蓋率':>8} | {'平均邊數':>8} | {'最大邊數':>8} |")
    print("|" + "|".join(["-" * w for w in [20, 6, 10, 10, 10, 10]]) + "|")

    for m in NF1_MODELS:
        sg = load_json(SG / m["sg"])
        edges_list = []
        for qid in isn_ids:
            sg_q = sg.get(qid)
            if sg_q:
                edges_list.append(sg_q.get("n_edges_kept", 0))
        total = len(edges_list)
        non_zero = sum(1 for e in edges_list if e > 0)
        avg = sum(edges_list) / total if total else 0
        mx  = max(edges_list) if edges_list else 0
        print(
            f"| {m['label']:<18} | {total:>4} | {non_zero:>8} | {pct(non_zero, total):>8} "
            f"| {avg:>8.1f} | {mx:>8} |"
        )

    print()
    print("※ 3 模型均從 329 題 NF1 eval 結果中取 ISN 子集")


# ─── main ──────────────────────────────────────────────────────────────────────
def main():
    print("exp_3 論文表格產出腳本")
    print("對應論文段落：§肆-八（實驗 3：Graph RAG 抗幻覺評估）")

    table1_main_result()
    table2_with_empty()
    table3_multi_scoring()
    table4_error_pattern()
    table5_coverage()

    print("\n" + "=" * 72)
    print("完成。所有表格均為 Markdown 格式，可直接複製貼入論文。")


if __name__ == "__main__":
    main()
