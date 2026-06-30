#!/usr/bin/env python3
"""NF1 = Per-model KG-GPT retrieval pipeline.

對應論文：§肆-八-X（NF1，每模型自做 Step 1 + Step 2b）

跟 F1 之差別：
- F1：Llama-70B 統一跑 Step 1+2b，產出共享 subgraph（4 模型共用）
- NF1：每個受測模型自做 Step 1+2b，產出該模型專屬之 subgraph

對齊 KG-GPT (Kim et al., 2023) 之 Step 1–2，但 prompt 改為 JSON schema 輸出（小模型友善）。

支援之模型（endpoint 由 .env 指定）：
- e4b      → LM Studio, env=LM_STUDIO_CHAT_URL, model_id=gemma-4-e4b-it
- gptoss   → Groq @ api.groq.com/openai/v1, model_id=openai/gpt-oss-20b（2 key pool）
- gemma31b → LM Studio, env=LM_STUDIO_CHAT_URL_ALT, model_id=google/gemma-4-31b
- llama70b → NVIDIA @ integrate.api.nvidia.com/v1, model_id=meta/llama-3.3-70b-instruct（6 key pool）

用法：
    python exp_3_nf1_pipeline.py --model e4b --questions data/question_bank_329.json \
        --output data/subgraph/subgraph_nf1_e4b.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompts import load_prompt

# ─── KG-GPT 對齊參數 ──────────────────────────────────────────────────────────
TOP_K_RELATIONS = 10
MAX_HOP = 3
TEMPERATURE = 0.0
TOP_P = 1.0
MAX_TOKENS_STEP1 = 1024
MAX_TOKENS_STEP2 = 256

# ─── JSON Schemas ─────────────────────────────────────────────────────────────
STEP1_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "string", "minLength": 1},
                    "entities": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 2,
                    },
                },
                "required": ["sentence", "entities"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 6,
        },
    },
    "required": ["sub_claims"],
    "additionalProperties": False,
}

STEP2_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_relations": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": TOP_K_RELATIONS,
        },
    },
    "required": ["selected_relations"],
    "additionalProperties": False,
}

# ─── Adapters ─────────────────────────────────────────────────────────────────
class BaseAdapter:
    name: str = "base"

    def call(self, system: str, user: str, schema: dict, max_tokens: int) -> str:
        """回傳 raw content（JSON 字串）；失敗回空。"""
        raise NotImplementedError


class LMStudioAdapter(BaseAdapter):
    def __init__(self, name: str, endpoint: str, model_id: str,
                 use_strict_schema: bool = True, use_json_object: bool = False):
        self.name = name
        self.endpoint = endpoint
        self.model_id = model_id
        # use_strict_schema=True  → json_schema strict（預設）
        # use_strict_schema=False + use_json_object=True → json_object（無 schema 但強制合法 JSON）
        # use_strict_schema=False + use_json_object=False → 無 response_format（靠 prompt 約束）
        self.use_strict_schema = use_strict_schema
        self.use_json_object = use_json_object

    def call(self, system: str, user: str, schema: dict, max_tokens: int) -> str:
        import requests
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "max_tokens": max_tokens,
        }
        if self.use_strict_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "nf1_step",
                    "strict": True,
                    "schema": schema,
                },
            }
        elif self.use_json_object:
            # 避開 strict schema decode 亂碼，但仍強制 LM Studio 輸出合法 JSON
            payload["response_format"] = {"type": "json_object"}
        attempt = 0
        while attempt < 4:
            try:
                resp = requests.post(self.endpoint,
                                     headers={"Content-Type": "application/json"},
                                     json=payload, timeout=120)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"] or ""
            except Exception as e:
                err = str(e).lower()
                attempt += 1
                wait = min(2 ** attempt, 30)
                if "429" in err or "rate" in err:
                    time.sleep(wait)
                    continue
                if attempt >= 4:
                    break
                time.sleep(wait)
        return ""


class GroqAdapter(BaseAdapter):
    """Groq OpenAI-compatible（多 key pool）."""

    def __init__(self, name: str, api_keys: list[str], model_id: str):
        self.name = name
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        self.model_id = model_id
        try:
            from openai import OpenAI  # noqa
        except ImportError as exc:
            raise RuntimeError("openai not installed; pip install openai") from exc
        self._client_q: queue.Queue = queue.Queue()
        for k in self.api_keys:
            self._client_q.put(self._build_client(k))

    @staticmethod
    def _build_client(api_key: str):
        from openai import OpenAI
        return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)

    def call(self, system: str, user: str, schema: dict, max_tokens: int) -> str:
        client = self._client_q.get()
        attempt = 0
        try:
            while attempt < 5:
                try:
                    resp = client.chat.completions.create(
                        model=self.model_id,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=TEMPERATURE,
                        top_p=TOP_P,
                        max_tokens=max_tokens,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "nf1_step",
                                "strict": True,
                                "schema": schema,
                            },
                        },
                    )
                    return resp.choices[0].message.content or ""
                except Exception as e:
                    err = str(e).lower()
                    attempt += 1
                    wait = min(2 ** attempt, 30)
                    if "429" in err or "rate" in err or "tpm" in err:
                        time.sleep(wait)
                        continue
                    if attempt >= 5:
                        break
                    time.sleep(wait)
        finally:
            self._client_q.put(client)
        return ""


class NVIDIAAdapter(BaseAdapter):
    def __init__(self, name: str, api_keys: list[str], model_id: str):
        self.name = name
        self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        self.model_id = model_id
        try:
            from openai import OpenAI  # noqa
        except ImportError as exc:
            raise RuntimeError("openai not installed") from exc
        self._client_q: queue.Queue = queue.Queue()
        for k in self.api_keys:
            self._client_q.put(self._build_client(k))

    @staticmethod
    def _build_client(api_key: str):
        from openai import OpenAI
        return OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)

    def call(self, system: str, user: str, schema: dict, max_tokens: int) -> str:
        # NVIDIA Llama-70B 不支援 strict JSON schema，但能依 prompt 輸出 JSON
        # 用 OpenAI SDK 之 response_format={"type": "json_object"} 提示
        client = self._client_q.get()
        attempt = 0
        try:
            while attempt < 4:
                try:
                    resp = client.chat.completions.create(
                        model=self.model_id,
                        messages=[
                            {"role": "system", "content": system + "\n請務必以 JSON 格式回答。"},
                            {"role": "user", "content": user},
                        ],
                        temperature=TEMPERATURE,
                        top_p=TOP_P,
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content or ""
                except Exception as e:
                    err = str(e).lower()
                    attempt += 1
                    wait = min(2 ** attempt, 30)
                    if "429" in err or "rate" in err:
                        time.sleep(wait)
                        continue
                    if attempt >= 4:
                        break
                    time.sleep(wait)
        finally:
            self._client_q.put(client)
        return ""


# ─── Model Registry ───────────────────────────────────────────────────────────
def build_adapter(model_key: str) -> BaseAdapter:
    if model_key == "phi":
        # strict=True：LM Studio 會收到請求，step1_ok=98%；中文輕微亂碼但 CONTAINS 模糊匹配仍可命中
        # 英文 entities（SQL injection/GPU/VPN 等 ISN 技術詞）不受 decode 亂碼影響
        return LMStudioAdapter(
            name="phi-4-mini-reasoning",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions"),
            model_id="microsoft/phi-4-mini-reasoning",
            use_strict_schema=True,
        )
    if model_key == "e4b":
        return LMStudioAdapter(
            name="gemma-4-e4b-it",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions"),
            model_id="gemma-4-e4b-it",
        )
    if model_key == "gptoss":
        # 2026-05-23 改：Groq 之 200K TPD 不足；改用本地 LM Studio @ .80
        # 注意：gpt-oss-20b GGUF + 中文 strict schema 會 decode 亂碼，故關 strict schema
        return LMStudioAdapter(
            name="gpt-oss-20b (local)",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL_ALT", os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions")),
            model_id="openai/gpt-oss-20b",
            use_strict_schema=False,
        )
    if model_key == "gptoss_groq":
        # 備援：Groq endpoint（保留 code 供日後若需要）
        groq_keys = [
            os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY"),
            os.getenv("GROQ_API_KEY_2"),
        ]
        return GroqAdapter(name="gpt-oss-20b", api_keys=groq_keys, model_id="openai/gpt-oss-20b")
    if model_key == "gemma31b":
        return LMStudioAdapter(
            name="gemma-4-31b",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL_ALT", os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions")),
            model_id="google/gemma-4-31b",
        )
    if model_key == "llama70b":
        nv_keys = [
            os.getenv("NVIDIA_API_KEY_1"),
            os.getenv("NVIDIA_API_KEY_2"),
            os.getenv("NVIDIA_API_KEY_3"),
            os.getenv("NVIDIA_API_KEY_4"),
            os.getenv("NVIDIA_API_KEY_5"),
            os.getenv("NVIDIA_API_KEY_6"),
        ]
        return NVIDIAAdapter(name="llama-3.3-70b-instruct", api_keys=nv_keys,
                             model_id="meta/llama-3.3-70b-instruct")
    raise ValueError(f"unknown model: {model_key}")


# 並行度（受 endpoint 物理約束）
MODEL_WORKERS = {
    "phi": 1,         # LM Studio @ .79 單機，reasoning model 較慢
    "e4b": 2,         # LM Studio @ .79 單機
    "gptoss": 4,      # Groq 2 keys，多 worker 競搶 keys
    "gemma31b": 2,    # LM Studio @ .80 單機
    "llama70b": 6,    # NVIDIA 6 keys
}


# ─── Cypher utilities ─────────────────────────────────────────────────────────
CYPHER_ENTITY_MATCH = """
MATCH (n:KGNode)
WHERE toLower(n.name) = toLower($name)
   OR toLower(n.name) CONTAINS toLower($name)
   OR toLower($name) CONTAINS toLower(n.name)
RETURN elementId(n) AS id, n.name AS name
LIMIT 1
"""

CYPHER_RELATIONS_OF = """
MATCH (n:KGNode)-[r]-(other:KGNode)
WHERE elementId(n) = $id
RETURN DISTINCT type(r) AS rel
"""

CYPHER_EXPAND_TRIPLES = """
MATCH (h:KGNode)-[r]->(t:KGNode)
WHERE elementId(h) = $head_id AND type(r) = $rel
RETURN elementId(h) AS head_id, h.name AS head, $rel AS relation,
       elementId(t) AS tail_id, t.name AS tail
LIMIT 50
"""

CYPHER_EXPAND_REVERSE = """
MATCH (h:KGNode)-[r]->(t:KGNode)
WHERE elementId(t) = $tail_id AND type(r) = $rel
RETURN elementId(h) AS head_id, h.name AS head, $rel AS relation,
       elementId(t) AS tail_id, t.name AS tail
LIMIT 50
"""


def entity_match(driver, name: str) -> dict | None:
    with driver.session() as sess:
        rec = sess.run(CYPHER_ENTITY_MATCH, name=name).single()
        return dict(rec) if rec else None


def relation_candidates(driver, entity_ids: list[str]) -> list[str]:
    all_rels: set[str] = set()
    with driver.session() as sess:
        for eid in entity_ids:
            rows = sess.run(CYPHER_RELATIONS_OF, id=eid)
            for r in rows:
                all_rels.add(r["rel"])
    return sorted(all_rels)


def expand_triples(driver, entity_ids: list[str], relations: list[str]) -> list[tuple]:
    triples: list[tuple] = []
    with driver.session() as sess:
        for eid in entity_ids:
            for rel in relations:
                for row in sess.run(CYPHER_EXPAND_TRIPLES, head_id=eid, rel=rel):
                    triples.append((row["head"], row["relation"], row["tail"],
                                    row["head_id"], row["tail_id"]))
                for row in sess.run(CYPHER_EXPAND_REVERSE, tail_id=eid, rel=rel):
                    triples.append((row["head"], row["relation"], row["tail"],
                                    row["head_id"], row["tail_id"]))
    return triples


# ─── graph_extractor (移植自 KG-GPT) ──────────────────────────────────────────
def graph_extractor(target_list: list[tuple]) -> list[tuple]:
    if not target_list:
        return target_list
    return_list = [target_list[0]]
    filter_dict = {"head": {}, "tail": {}}
    h0, r0, t0 = target_list[0][0], target_list[0][1], target_list[0][2]
    filter_dict["head"][h0] = [r0]
    filter_dict["tail"][t0] = [r0]
    for tar in target_list[1:]:
        h, r, t = tar[0], tar[1], tar[2]
        if tar in return_list:
            continue
        if h in filter_dict["head"] and r in filter_dict["head"][h]:
            continue
        if t in filter_dict["tail"] and r in filter_dict["tail"][t]:
            continue
        return_list.append(tar)
        filter_dict["head"].setdefault(h, []).append(r)
        filter_dict["tail"].setdefault(t, []).append(r)
    return return_list


# ─── Step parsers (含 fallback) ───────────────────────────────────────────────
def parse_step1(raw: str) -> list[dict]:
    """JSON-first parse；失敗 fallback 至 free-text "1. (...) Entity set:[...]" 格式。"""
    if not raw:
        return []
    # JSON 嘗試
    for candidate in (raw, _extract_json_block(raw)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            arr = obj.get("sub_claims") if isinstance(obj, dict) else None
            if isinstance(arr, list):
                out = []
                for it in arr:
                    if not isinstance(it, dict):
                        continue
                    s = str(it.get("sentence", "")).strip()
                    ents = it.get("entities", []) or []
                    ents = [str(e).strip() for e in ents if str(e).strip()][:2]
                    if s and ents:
                        out.append({"sentence": s, "entities": ents})
                if out:
                    return out
        except json.JSONDecodeError:
            pass
    # free-text fallback
    out = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"^\d+\.\s*(.+?)\s*[,，]?\s*Entity\s*set\s*[:：]\s*\[(.*?)\]\s*$", line)
        if not m:
            continue
        sent = m.group(1).strip().rstrip(",，。 ")
        ents = [e.strip().strip("'\"") for e in m.group(2).split("##") if e.strip()]
        ents = [e for e in ents if e][:2]
        if sent and ents:
            out.append({"sentence": sent, "entities": ents})
    return out


def parse_step2(raw: str, candidates: list[str]) -> list[str]:
    """JSON-first parse；失敗 fallback 至 [...] 抽取。"""
    if not raw:
        return []
    for cand_text in (raw, _extract_json_block(raw)):
        if not cand_text:
            continue
        try:
            obj = json.loads(cand_text)
            if isinstance(obj, dict) and "selected_relations" in obj:
                rels = obj["selected_relations"]
                if isinstance(rels, list):
                    out = [str(r).strip().strip("'\"") for r in rels if str(r).strip()]
                    valid = [r for r in out if r in candidates]
                    if valid:
                        return valid[:TOP_K_RELATIONS]
        except json.JSONDecodeError:
            pass
    # 抓 [ ... ] 之內容
    m = re.search(r"\[([^\[\]]*)\]", raw, re.DOTALL)
    if m:
        parts = [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
        valid = [r for r in parts if r in candidates]
        if valid:
            return valid[:TOP_K_RELATIONS]
    return []


def _extract_json_block(text: str) -> str | None:
    """從含 markdown 之回應抽 ```json ... ``` 或最外層 { ... }."""
    if not text:
        return None
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group()
    return None


# ─── 主管線：題目 → evidence triples ─────────────────────────────────────────
STEP1_SYSTEM = load_prompt("exp_3/nf1_step1_system.md")
STEP2_SYSTEM = load_prompt("exp_3/nf1_step2_system.md")


def process_one_question(question: dict, driver, adapter: BaseAdapter,
                         prompt_step1: str, prompt_step2: str) -> dict:
    qid = question["qid"]
    claim = question["stem"]

    # Step 1
    s1_prompt = prompt_step1.replace("<<<<CLAIM>>>>", claim)
    s1_raw = adapter.call(STEP1_SYSTEM, s1_prompt, STEP1_SCHEMA, MAX_TOKENS_STEP1)
    sub_claims = parse_step1(s1_raw)
    if not sub_claims:
        sub_claims = [{"sentence": claim, "entities": []}]
    step1_parse_ok = bool(parse_step1(s1_raw))

    # Step 2 per sub-claim
    all_evidence: list[tuple] = []
    matched_global: list[str] = []
    used_rels: list[str] = []
    step2b_calls = 0
    step2b_parse_ok = 0

    for sc in sub_claims:
        entity_names = sc.get("entities", [])
        sentence = sc.get("sentence", "")
        if not entity_names:
            continue
        # Step 2a
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

        # Step 2b
        if len(cands) <= TOP_K_RELATIONS:
            selected = cands
        else:
            s2_prompt = (prompt_step2
                         .replace("<<<<TOP_K>>>>", str(TOP_K_RELATIONS))
                         .replace("<<<<SENTENCE>>>>", sentence)
                         .replace("<<<<RELATION_SET>>>>", str(cands)))
            s2_raw = adapter.call(STEP2_SYSTEM, s2_prompt, STEP2_SCHEMA, MAX_TOKENS_STEP2)
            step2b_calls += 1
            picked = parse_step2(s2_raw, cands)
            if picked:
                step2b_parse_ok += 1
                selected = picked
            else:
                selected = cands[:TOP_K_RELATIONS]
        used_rels.extend(selected)

        # 展開三元組
        triples = expand_triples(driver, [e["id"] for e in matched], selected)
        all_evidence.extend(triples)

    # multi-hop chaining (1 階)
    if MAX_HOP >= 2 and all_evidence:
        tail_ids = {tr[4] for tr in all_evidence}
        chain_rels = list(set(used_rels))[:TOP_K_RELATIONS]
        for tail_id in list(tail_ids)[:30]:
            with driver.session() as sess:
                for rel in chain_rels:
                    for row in sess.run(CYPHER_EXPAND_TRIPLES, head_id=tail_id, rel=rel):
                        all_evidence.append((row["head"], row["relation"], row["tail"],
                                             row["head_id"], row["tail_id"]))

    # 去重 + graph_extractor
    seen = set()
    unique = []
    for tr in all_evidence:
        key = (tr[0], tr[1], tr[2])
        if key in seen:
            continue
        seen.add(key)
        unique.append(tr)
    final = graph_extractor(unique)

    context_text = "\n".join(f"{tr[0]} --[{tr[1]}]--> {tr[2]}" for tr in final) or "(無相關三元組)"

    return {
        "qid": qid,
        "sub_claims": sub_claims,
        "entities_matched": list(dict.fromkeys(matched_global)),
        "relations_used": list(dict.fromkeys(used_rels)),
        "n_evidence_pre_extractor": len(unique),
        "n_evidence_kept": len(final),
        "subgraph": {
            "evidence": [
                {"head": tr[0], "relation": tr[1], "tail": tr[2]}
                for tr in final
            ],
        },
        "context_text": context_text,
        "n_nodes_kept": len({tr[0] for tr in final} | {tr[2] for tr in final}),
        "n_edges_kept": len(final),
        "_step1_parse_ok": step1_parse_ok,
        "_step2b_calls": step2b_calls,
        "_step2b_parse_ok": step2b_parse_ok,
    }


# ─── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True,
                        choices=["phi", "e4b", "gptoss", "gptoss_groq", "gemma31b", "llama70b"])
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--n_workers", type=int, default=0,
                        help="0 = 採模型預設")
    parser.add_argument("--limit", type=int, default=0,
                        help="僅跑前 N 題（smoke test 用），0=全跑")
    args = parser.parse_args()

    adapter = build_adapter(args.model)
    n_workers = args.n_workers or MODEL_WORKERS.get(args.model, 2)
    print(f"[NF1] model={args.model}  adapter={adapter.name}  workers={n_workers}")
    print(f"  TOP_K={TOP_K_RELATIONS}  MAX_HOP={MAX_HOP}  temperature={TEMPERATURE}")

    prompt_step1 = load_prompt("exp_3/nf1_step1_sentence_divide_json_zh.txt")
    prompt_step2 = load_prompt("exp_3/nf1_step2_relation_retrieval_json_zh.txt")

    qs = json.loads(args.questions.read_text(encoding="utf-8"))
    if args.limit > 0:
        qs = qs[:args.limit]
    print(f"  題庫 {len(qs)} 題")

    done_map: dict = {}
    if args.output.exists():
        try:
            done_map = json.loads(args.output.read_text(encoding="utf-8"))
            print(f"  [Resume] 已有 {len(done_map)} 題")
        except Exception:
            pass

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    todo = [q for q in qs if q["qid"] not in done_map]
    print(f"  待處理: {len(todo)} 題")

    write_lock = threading.Lock()

    def _worker(q: dict):
        try:
            result = process_one_question(q, driver, adapter, prompt_step1, prompt_step2)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[:400]
            result = {
                "qid": q["qid"],
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "context_text": "(處理失敗)",
                "n_nodes_kept": 0,
                "n_edges_kept": 0,
                "subgraph": {"evidence": []},
            }
            print(f"  [err] {q['qid']}: {tb[:150]}")
        with write_lock:
            done_map[q["qid"]] = result
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(done_map, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        return q["qid"]

    if todo:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(_worker, q) for q in todo]
            done = 0
            for fut in as_completed(futures):
                done += 1
                if done % 10 == 0 or done == len(todo):
                    print(f"  進度 {done}/{len(todo)}")

    driver.close()

    # 統計
    ok = [v for v in done_map.values() if "error" not in v]
    err = [v for v in done_map.values() if "error" in v]
    empty = [v for v in ok if v.get("n_edges_kept", 0) == 0]
    s1_ok = sum(1 for v in ok if v.get("_step1_parse_ok"))
    s2_total = sum(v.get("_step2b_calls", 0) for v in ok)
    s2_ok = sum(v.get("_step2b_parse_ok", 0) for v in ok)
    if ok:
        edges = [v.get("n_edges_kept", 0) for v in ok]
        print(f"\n[Done] {len(done_map)} 題；error {len(err)} 空 {len(empty)}")
        print(f"  Step1 JSON parse OK: {s1_ok}/{len(ok)} ({s1_ok/len(ok)*100:.1f}%)")
        print(f"  Step2b JSON parse OK: {s2_ok}/{s2_total} ({s2_ok/max(1,s2_total)*100:.1f}%)")
        print(f"  邊：平均 {sum(edges)/len(edges):.1f}  最大 {max(edges)}")
    print(f"  輸出: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


