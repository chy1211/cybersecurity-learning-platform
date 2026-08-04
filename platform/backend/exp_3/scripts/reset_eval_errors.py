#!/usr/bin/env python3
"""掃 eval_*_NF1.json 之 errors+empty，刪除對應 (qid, condition) entry，讓 eval_batch resume 補跑."""
from __future__ import annotations
import argparse, json
from pathlib import Path


def reset_errors(eval_path: Path) -> tuple[int, list[str], list[str]]:
    """返回 (刪除數, 受影響 LLM qids, 受影響 RAG qids)."""
    d = json.loads(eval_path.read_text(encoding="utf-8"))
    rm_llm, rm_rag = [], []
    for qid, by_cond in list(d.items()):
        if "llm_only" in by_cond:
            r = by_cond["llm_only"]
            if "_api_error" in r or "_parse_error" in r or not r.get("answer_norm"):
                del by_cond["llm_only"]
                rm_llm.append(qid)
        if "graph_rag" in by_cond:
            r = by_cond["graph_rag"]
            if "_api_error" in r or "_parse_error" in r or not r.get("answer_norm"):
                del by_cond["graph_rag"]
                rm_rag.append(qid)
        if not by_cond:
            del d[qid]
    eval_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(rm_llm) + len(rm_rag), rm_llm, rm_rag


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="e4b,gptoss,gemma31b,llama70b")
    parser.add_argument("--eval_dir", default="data/eval_results")
    parser.add_argument("--suffix", default="_NF1")
    args = parser.parse_args()

    for m in args.models.split(","):
        m = m.strip()
        p = Path(args.eval_dir) / f"eval_{m}{args.suffix}.json"
        if not p.exists():
            print(f"[{m}] (缺檔)"); continue
        n, ll, lr = reset_errors(p)
        print(f"[{m}] 刪 LLM={len(ll)}  RAG={len(lr)}  合計={n}")


if __name__ == "__main__":
    main()
