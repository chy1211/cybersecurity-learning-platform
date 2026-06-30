#!/usr/bin/env python3
"""NF1 Step 1 失敗題目 retry 1 次（temperature=0.3 微擾）.

對 subgraph_nf1_{model}.json 中 _step1_parse_ok=False 之題目：
1. 用同一 adapter 重跑 Step 1（temperature=0.3）
2. 若 parse 成功且 entities 非空 → 重做 Step 2a/2b/expand/multi-hop/graph_extractor
3. 覆寫該 qid 之 subgraph entry，加 _step1_retry=True
4. 若仍失敗 → 保留原 fallback 紀錄，加 _step1_retry_failed=True

用法：
    python scripts/nf1_retry_step1.py --model gemma31b
    python scripts/nf1_retry_step1.py --model all

注意：retry 後若該題已有 eval 結果，需手動刪除 eval_{model}_NF1.json 中該 qid 之 graph_rag 條目，
讓 eval_batch resume 邏輯重跑。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 從 NF1 pipeline 借用工具
from exp_3_nf1_pipeline import (
    build_adapter, load_prompt,
    STEP1_SCHEMA, STEP2_SCHEMA,
    STEP1_SYSTEM, STEP2_SYSTEM,
    TOP_K_RELATIONS, MAX_HOP,
    MAX_TOKENS_STEP1, MAX_TOKENS_STEP2,
    parse_step1, parse_step2,
    entity_match, relation_candidates, expand_triples, graph_extractor,
    CYPHER_EXPAND_TRIPLES,
)


def retry_one_question(question: dict, driver, adapter, prompt_step1, prompt_step2,
                       retry_temperature: float = 0.3) -> dict | None:
    """重跑 Step 1（高溫微擾）→ 若成功則重做下游檢索；返回新 subgraph entry 或 None（仍失敗）。"""
    qid = question["qid"]
    claim = question["stem"]
    s1_prompt = prompt_step1.replace("<<<<CLAIM>>>>", claim)

    # 暫時調高 temperature 重跑 Step 1
    # 對 LMStudioAdapter / GroqAdapter / NVIDIAAdapter 直接覆寫 payload temperature 比較難
    # 因此我們 patch 一個 call_with_temperature 方法（用 closures）
    raw = _call_with_temperature(adapter, STEP1_SYSTEM, s1_prompt, STEP1_SCHEMA,
                                 MAX_TOKENS_STEP1, retry_temperature)
    sub_claims = parse_step1(raw)
    if not sub_claims:
        return None  # 仍失敗

    # 下游檢索（與 process_one_question 對齊）
    all_evidence = []
    matched_global = []
    used_rels = []
    step2b_calls = 0
    step2b_ok = 0

    for sc in sub_claims:
        entity_names = sc.get("entities", [])
        sentence = sc.get("sentence", "")
        if not entity_names:
            continue
        matched = []
        for ename in entity_names:
            m = entity_match(driver, ename)
            if m:
                matched.append(m)
        if not matched:
            continue
        cands = relation_candidates(driver, [e["id"] for e in matched])
        if not cands:
            continue
        matched_global.extend(e["name"] for e in matched)

        if len(cands) <= TOP_K_RELATIONS:
            selected = cands
        else:
            s2_prompt = (prompt_step2
                         .replace("<<<<TOP_K>>>>", str(TOP_K_RELATIONS))
                         .replace("<<<<SENTENCE>>>>", sentence)
                         .replace("<<<<RELATION_SET>>>>", str(cands)))
            s2_raw = _call_with_temperature(adapter, STEP2_SYSTEM, s2_prompt, STEP2_SCHEMA,
                                            MAX_TOKENS_STEP2, retry_temperature)
            step2b_calls += 1
            picked = parse_step2(s2_raw, cands)
            if picked:
                step2b_ok += 1
                selected = picked
            else:
                selected = cands[:TOP_K_RELATIONS]
        used_rels.extend(selected)

        triples = expand_triples(driver, [e["id"] for e in matched], selected)
        all_evidence.extend(triples)

    # multi-hop (1 階)
    if MAX_HOP >= 2 and all_evidence:
        tail_ids = {tr[4] for tr in all_evidence}
        chain_rels = list(set(used_rels))[:TOP_K_RELATIONS]
        for tail_id in list(tail_ids)[:30]:
            with driver.session() as sess:
                for rel in chain_rels:
                    for row in sess.run(CYPHER_EXPAND_TRIPLES, head_id=tail_id, rel=rel):
                        all_evidence.append((row["head"], row["relation"], row["tail"],
                                             row["head_id"], row["tail_id"]))

    seen = set()
    unique = []
    for tr in all_evidence:
        key = (tr[0], tr[1], tr[2])
        if key in seen:
            continue
        seen.add(key)
        unique.append(tr)
    final = graph_extractor(unique)

    return {
        "qid": qid,
        "sub_claims": sub_claims,
        "entities_matched": list(dict.fromkeys(matched_global)),
        "relations_used": list(dict.fromkeys(used_rels)),
        "n_evidence_pre_extractor": len(unique),
        "n_evidence_kept": len(final),
        "subgraph": {
            "evidence": [{"head": tr[0], "relation": tr[1], "tail": tr[2]} for tr in final],
        },
        "context_text": "\n".join(f"{tr[0]} --[{tr[1]}]--> {tr[2]}" for tr in final) or "(無相關三元組)",
        "n_nodes_kept": len({tr[0] for tr in final} | {tr[2] for tr in final}),
        "n_edges_kept": len(final),
        "_step1_parse_ok": True,
        "_step1_retry": True,
        "_step2b_calls": step2b_calls,
        "_step2b_parse_ok": step2b_ok,
    }


def _call_with_temperature(adapter, system, user, schema, max_tokens, temperature):
    """monkey-patch adapter 之 temperature。用後恢復。"""
    # 因 adapter.call 內部 hard-code TEMPERATURE，我們用 monkey-patch 改 module-level constant
    import exp_3_nf1_pipeline as nf1_mod
    saved = nf1_mod.TEMPERATURE
    nf1_mod.TEMPERATURE = temperature
    try:
        return adapter.call(system, user, schema, max_tokens)
    finally:
        nf1_mod.TEMPERATURE = saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True,
                        choices=["e4b", "gptoss", "gemma31b", "llama70b", "all"])
    parser.add_argument("--questions", default="data/question_bank_329.json")
    parser.add_argument("--subgraph_dir", default="data/subgraph")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--temperature", type=float, default=0.3)
    args = parser.parse_args()

    qs_list = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    qs_by_id = {q["qid"]: q for q in qs_list}

    models = ["e4b", "gptoss", "gemma31b", "llama70b"] if args.model == "all" else [args.model]
    prompt_step1 = load_prompt("exp_3/nf1_step1_sentence_divide_json_zh.txt")
    prompt_step2 = load_prompt("exp_3/nf1_step2_relation_retrieval_json_zh.txt")

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    for m in models:
        sg_path = Path(args.subgraph_dir) / f"subgraph_nf1_{m}.json"
        if not sg_path.exists():
            print(f"[{m}] 跳過：{sg_path} 不存在")
            continue
        sg = json.loads(sg_path.read_text(encoding="utf-8"))
        fail_qids = [qid for qid, v in sg.items()
                     if v.get("_step1_parse_ok") is False or
                     (not v.get("_step1_parse_ok") and not v.get("error"))]
        # 注意：原版未跑出之題不會在這裡（已預先過濾）。判斷邏輯：_step1_parse_ok=False
        fail_qids = [qid for qid, v in sg.items() if v.get("_step1_parse_ok") is False]
        print(f"\n[{m}] step1 失敗題: {len(fail_qids)}")
        if not fail_qids:
            continue

        adapter = build_adapter(m)
        retry_ok = 0
        retry_fail = 0
        for qid in fail_qids:
            q = qs_by_id.get(qid)
            if not q:
                continue
            try:
                new_entry = retry_one_question(q, driver, adapter, prompt_step1, prompt_step2,
                                               retry_temperature=args.temperature)
            except Exception as e:
                print(f"  [err] {qid}: {type(e).__name__}: {str(e)[:100]}")
                continue
            if new_entry is not None:
                sg[qid] = new_entry
                retry_ok += 1
                print(f"  [{qid}] 救回 n_edges={new_entry['n_edges_kept']}")
            else:
                sg[qid]["_step1_retry_failed"] = True
                retry_fail += 1
                print(f"  [{qid}] retry 仍失敗")

        sg_path.write_text(json.dumps(sg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{m}] retry 救回 {retry_ok}/{len(fail_qids)}（仍失敗 {retry_fail}）")

    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
