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
- gemma31b → Google AI Studio 直連（GEMINI_API_KEYS 多金鑰, model_id=gemma-4-31b-it；2026-07-12 拍板，原 .80 LM Studio 部署之 model id 已漂移為 -qat）
- llama70b → NVIDIA @ integrate.api.nvidia.com/v1, model_id=meta/llama-3.1-70b-instruct（動態 key pool＝.env 之 NVIDIA_API_KEY_<N>，worker 數等比；2026-07-12 拍板 3.3→3.1）

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
from exp_3.b4.entity_linker import EntityLinker, LinkerConfig
from exp_3.b4.evidence_ranking import prompt_triples, rank_and_budget_evidence
from exp_3.b4.mention_extraction import (
    MentionExtractionError,
    build_step1_input,
    parse_mention_payload,
)
from exp_3.b4.model_node_linking import build_prompt as build_nodelink_prompt
from exp_3.b4.model_node_linking import parse_choices as parse_node_choices
from exp_3.b4.question_normalization import normalize_question_set
from exp_3.b4.relation_selection import RelationSelectionError, parse_relation_selection
from exp_3.b4.semantic_index import (
    DEFAULT_EMBEDDING_MODEL,
    OpenAIEmbeddingClient,
    build_semantic_index,
)
from exp_3.b4.subgraph import expand_subgraph

# ─── KG-GPT 對齊參數 ──────────────────────────────────────────────────────────
TOP_K_RELATIONS = 10
MAX_HOP = 2
MAX_TRIPLES_PER_NODE = 50
MAX_EVIDENCE_PER_QUESTION = 100
TEMPERATURE = 0.0
TOP_P = 1.0
MAX_TOKENS_STEP1 = 32768
MAX_TOKENS_STEP2 = 32768
MAX_TOKENS_NODELINK = 32768

# ─── JSON Schemas ─────────────────────────────────────────────────────────────
STEP1_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subclaim_id": {"type": "string", "minLength": 1},
                    "text": {"type": "string", "minLength": 1},
                    "mentions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "minLength": 1},
                                "origin": {
                                    "type": "string",
                                    "enum": [
                                        "stem",
                                        "option_A",
                                        "option_B",
                                        "option_C",
                                        "option_D",
                                    ],
                                },
                                "source_span": {"type": "string", "minLength": 1},
                            },
                            "required": ["text", "origin", "source_span"],
                            "additionalProperties": False,
                        },
                        "maxItems": 20,
                    },
                },
                "required": ["subclaim_id", "text", "mentions"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 10,
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
        "decision_reason": {"type": "string", "minLength": 1},
    },
    "required": ["selected_relations", "decision_reason"],
    "additionalProperties": False,
}

# Route-2 model-in-the-loop node linking: the evaluated model picks one node id
# per pending mention from a bounded candidate set, or null (fail closed).
NODELINK_SYSTEM = "你是嚴謹的資安知識圖譜實體連結器，只輸出符合 schema 的 JSON。"
NODELINK_SCHEMA = {
    "type": "object",
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "element_id": {"type": ["string", "null"]},
                },
                "required": ["index", "element_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["choices"],
    "additionalProperties": False,
}

# ─── Adapters ─────────────────────────────────────────────────────────────────
class BaseAdapter:
    name: str = "base"

    def call(self, system: str, user: str, schema: dict, max_tokens: int,
              temperature: float | None = None) -> str:
        """回傳 raw content（JSON 字串）；失敗回空。temperature 未指定時各
        adapter 用全域 TEMPERATURE；由外層重試（見 _call_and_parse）在偵測到
        解析失敗時逐次微調帶入，用來跳出同參數必重現的確定性錯誤輸出。"""
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

    def call(self, system: str, user: str, schema: dict, max_tokens: int,
              temperature: float | None = None) -> str:
        import requests
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": TEMPERATURE if temperature is None else temperature,
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

    def call(self, system: str, user: str, schema: dict, max_tokens: int,
              temperature: float | None = None) -> str:
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
                        temperature=TEMPERATURE if temperature is None else temperature,
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


class GoogleAdapter(BaseAdapter):
    """Google AI Studio 直連（GenAI SDK，多金鑰 round-robin pool）。
    2026-07-12 使用者拍板：gemma31b 由 LM Studio(.80) 改直連 AI Studio
    （gemma-4-31b-it 原始權重），與 ETL 02 萃取同路線。
    Gemma API 不掛 response_format schema；靠 prompt 約束＋上層 JSON 萃取。"""

    def __init__(self, name: str, api_keys: list[str], model_id: str):
        self.name = name
        self.api_keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
        if not self.api_keys:
            raise RuntimeError("GoogleAdapter: no Gemini keys (set GEMINI_API_KEYS)")
        self.model_id = model_id
        self.endpoint = "https://generativelanguage.googleapis.com/v1beta"  # 資訊性
        try:
            from google import genai  # noqa
        except ImportError as exc:
            raise RuntimeError("google-genai not installed; pip install google-genai") from exc
        from google import genai
        self._client_q: queue.Queue = queue.Queue()
        for k in self.api_keys:
            self._client_q.put(genai.Client(api_key=k))

    def call(self, system: str, user: str, schema: dict, max_tokens: int,
              temperature: float | None = None) -> str:
        from google.genai import types
        client = self._client_q.get()
        attempt = 0
        base_temperature = TEMPERATURE if temperature is None else temperature
        try:
            while attempt < 4:
                # gemma-4-31b-it 不支援關閉/限制 thinking_config；部分題目的思考長度
                # 在同一 temperature 下會確定性地耗盡整個 max_output_tokens（finish_reason
                # =MAX_TOKENS 且無實際輸出）。單純重試同參數必重現同一結果，故此處在偵測到
                # 這種「全部預算燒在 thinking、無輸出」的情況時改用微調過的 temperature 重試，
                # 以跳出該次確定性推理路徑。
                call_temperature = (
                    base_temperature if attempt == 0
                    else min(base_temperature + 0.2 * attempt, 0.8)
                )
                try:
                    resp = client.models.generate_content(
                        model=self.model_id,
                        contents=user,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            temperature=call_temperature,
                            top_p=TOP_P,
                            max_output_tokens=max_tokens,
                        ),
                    )
                    text = (resp.text or "") if hasattr(resp, "text") else ""
                    if text:
                        return text
                    candidates = getattr(resp, "candidates", None) or []
                    finish_reason = str(candidates[0].finish_reason) if candidates else ""
                    attempt += 1
                    if "MAX_TOKENS" in finish_reason and attempt < 4:
                        continue
                    return ""
                except Exception as e:
                    err = str(e).lower()
                    attempt += 1
                    wait = min(2 ** attempt, 30)
                    if ("429" in err or "rate" in err or "quota" in err
                            or "resource_exhausted" in err):
                        time.sleep(wait)
                        # 額度/限流：換下一把金鑰再試（round-robin，同 02 萃取策略）
                        self._client_q.put(client)
                        client = self._client_q.get()
                        continue
                    if attempt >= 4:
                        break
                    time.sleep(wait)
        finally:
            self._client_q.put(client)
        return ""


def _load_gemini_keys() -> list[str]:
    """GEMINI_API_KEYS（逗號/分號/換行分隔）＋單數名 fallback；與 ETL 02 同款。"""
    keys: list[str] = []
    multi = os.getenv("GEMINI_API_KEYS") or os.getenv("GOOGLE_API_KEYS") or ""
    for part in re.split(r"[,\n;]", multi):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        k = (os.getenv(env_name) or "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def _load_nvidia_keys() -> list[str]:
    """動態掃描 NVIDIA_API_KEY_<N>（可跳號、依 N 排序）；與 MatchGPT run_matchgpt.py 同款。
    有幾把就用幾把，llama70b 之 worker 數等比自動跟隨（見 MODEL_WORKERS）。"""
    prefix = "NVIDIA_API_KEY_"
    return [
        v.strip()
        for _n, v in sorted(
            (int(k[len(prefix):]), v)
            for k, v in os.environ.items()
            if k.startswith(prefix) and k[len(prefix):].isdigit() and v.strip()
        )
    ]


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

    def call(self, system: str, user: str, schema: dict, max_tokens: int,
              temperature: float | None = None) -> str:
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
                        temperature=TEMPERATURE if temperature is None else temperature,
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
        # strict=True：保留結構化輸出契約；若回覆不符合 schema，交由硬錯誤處理。
        return LMStudioAdapter(
            name="phi-4-mini-reasoning",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions"),
            model_id="microsoft/phi-4-mini-reasoning",
            use_strict_schema=True,
        )
    if model_key == "e4b":
        # 2026-07-13：non-strict 曾被嘗試（比照 gptoss）以解決少數候選數較多批次
        # 的截斷 JSON，但正式 356 題跑批顯示 e4b（弱於 gptoss）在無 schema 引導下
        # 大量吐出空回應（empty node-linking response，33% 錯誤率，遠高於
        # strict schema 下建構集的 3.6%）。改回 strict：對 e4b 而言 schema 引導
        # 帶來的合法輸出率提升，明顯壓過其偶發截斷 JSON 的代價。
        return LMStudioAdapter(
            name="gemma-4-e4b-it",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions"),
            model_id="gemma-4-e4b-it",
            use_strict_schema=True,
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
        # 2026-07-13：AI Studio 直連版對正式 356 題跑批不穩定（thinking 模式偶爾把
        # 整個 max_output_tokens 燒在 reasoning、無文字輸出），改本地 LM Studio @ .80
        # 非量化版後穩定但太慢（單機序列、5090 滿載，~5-6 分鐘/題，356 題估 11+ 小時）。
        # 使用者確認 NVIDIA NIM 亦有代管 google/gemma-4-31b-it；實測兩次呼叫皆
        # finish_reason=stop、content 正常（1.87s～30s，視 reasoning token 量），改走
        # NVIDIA NIM，比照 llama70b 用同一組 NVIDIA_API_KEY_<N> 多金鑰並行池，
        # 換取大幅平行化（本地單機序列 → 最多 7-way 並行）。
        nv_keys = _load_nvidia_keys()
        return NVIDIAAdapter(name="gemma-4-31b-it (NVIDIA NIM)", api_keys=nv_keys,
                             model_id="google/gemma-4-31b-it")
    if model_key == "llama70b":
        # 動態讀 .env 之 NVIDIA_API_KEY_<N>（有幾把用幾把；與 MatchGPT 同款）。
        nv_keys = _load_nvidia_keys()
        # 2026-07-12 使用者拍板：受測 70B 由 3.3 改 3.1（與全鏈判定模型同款）。
        return NVIDIAAdapter(name="llama-3.1-70b-instruct", api_keys=nv_keys,
                             model_id="meta/llama-3.1-70b-instruct")
    raise ValueError(f"unknown model: {model_key}")


# 並行度（受 endpoint 物理約束）
MODEL_WORKERS = {
    "phi": 1,         # LM Studio @ .79 單機，reasoning model 較慢
    "e4b": 1,         # LM Studio @ .79 單機；2026-07-13 正式跑批實測 2 worker 併發
                      # 會讓 .79 server log 出現 "Channel Error"、client 端收到空回應
                      # （NodeLinkingError/MentionExtractionError: empty response），
                      # 與 phi 同款單機同因，降為 1 避免併發搶連線。
    "gptoss": 1,      # LM Studio @ .80 單機；實測 4 worker 併發會讓輸出偶爾交錯/截斷（invalid JSON），降為 1 避免併發問題
    "gemma31b": len(_load_nvidia_keys()) or 1,  # 2026-07-13 改 NVIDIA NIM；worker 數 = .env 金鑰數（與 llama70b 共用同一組 key，llama70b 已跑完不衝突）
    "llama70b": len(_load_nvidia_keys()) or 1,  # NVIDIA：worker 數 = .env 金鑰數（動態，與 MatchGPT 同款）
}


# ─── Cypher utilities ─────────────────────────────────────────────────────────
CYPHER_ALL_NODES = """
MATCH (n:KGNode)
RETURN elementId(n) AS element_id, n.name AS name, n.type AS type
ORDER BY elementId(n)
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


def load_kg_nodes(driver) -> list[dict]:
    with driver.session() as sess:
        return [dict(row) for row in sess.run(CYPHER_ALL_NODES)]


def build_entity_linker(
    driver,
    aliases_path: Path,
    config_path: Path,
    *,
    nodes: list[dict] | None = None,
    semantic_index=None,
    semantic_client=None,
) -> EntityLinker:
    aliases_payload = json.loads(aliases_path.read_text(encoding="utf-8"))
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    aliases = aliases_payload.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("entity_aliases.json aliases must be an object")
    nodes = nodes if nodes is not None else load_kg_nodes(driver)
    semantic_provider = None
    if semantic_index is not None or semantic_client is not None:
        if semantic_index is None or semantic_client is None:
            raise ValueError("semantic index and client must be configured together")
        semantic_provider = semantic_index.provider(semantic_client)
    return EntityLinker(
        nodes,
        aliases=aliases,
        config=LinkerConfig.from_mapping(config_payload),
        semantic_provider=semantic_provider,
    )


def relation_candidates(driver, entity_ids: list[str]) -> list[str]:
    all_rels: set[str] = set()
    with driver.session() as sess:
        for eid in entity_ids:
            rows = sess.run(CYPHER_RELATIONS_OF, id=eid)
            for r in rows:
                all_rels.add(r["rel"])
    return sorted(all_rels)


def neo4j_fetch_edges(driver, node_ids: list[str], relations: list[str]) -> list[dict]:
    edges: list[dict] = []
    with driver.session() as sess:
        for eid in sorted(set(node_ids)):
            for rel in sorted(set(relations)):
                for row in sess.run(CYPHER_EXPAND_TRIPLES, head_id=eid, rel=rel):
                    edges.append(dict(row))
                for row in sess.run(CYPHER_EXPAND_REVERSE, tail_id=eid, rel=rel):
                    edges.append(dict(row))
    return edges


# ─── 主管線：題目 → evidence triples ─────────────────────────────────────────
STEP1_SYSTEM = load_prompt("exp_3/nf1_step1_system.md")
STEP2_SYSTEM = load_prompt("exp_3/nf1_step2_system.md")

PARSE_RETRY_ATTEMPTS = 10


def _call_and_parse(adapter: BaseAdapter, system: str, user: str, schema: dict,
                     max_tokens: int, parse_fn):
    """呼叫模型並解析回應；解析失敗（非 schema 違規，而是模型偶發的空回應／
    格式錯亂 JSON）時重打幾次。這類間歇性故障（gpt-oss 偶爾多吐一段文字、
    gemma31b 少數題目思考預算仍不夠）在同一 adapter.call() 內部重試不保證能
    修好，故在更高層對「呼叫+解析」整組重試。

    溫度固定在 0 的 adapter（LM Studio／NVIDIA）對同一題目有時會確定性地
    重現同一個格式錯誤（例如巢狀錯亂的 sub_claims，或 relation selection
    堅持挑一個不在候選集內、聽起來合理的關係名），單純重打會拿到一模一樣
    的壞輸出。故從第二次起微調 temperature，逼模型跳出該次確定性的解碼
    路徑；2026-07-13 正式跑批發現部分個案在 0.8 上限內仍會每次收斂回同一個
    錯誤答案，故拉高上限到 1.2、attempts 拉到 10 次，給更多機會跳脫。
    GoogleAdapter 內部另有自己的 thinking-budget 專用重試，這裡傳入的
    temperature 會再疊加上去，不衝突。"""

    last_exc: Exception | None = None
    for attempt in range(PARSE_RETRY_ATTEMPTS):
        temperature = None if attempt == 0 else min(0.15 * attempt, 1.2)
        raw = adapter.call(system, user, schema, max_tokens, temperature=temperature)
        try:
            return parse_fn(raw)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, re-raised below
            last_exc = exc
            continue
    raise last_exc


def process_one_question(question: dict, driver, adapter: BaseAdapter,
                         linker: EntityLinker, prompt_step1: str,
                         prompt_step2: str, prompt_nodelink: str) -> dict:
    qid = question["qid"]
    question_started = time.perf_counter()

    # Step 1: every evaluated model receives the same stem + A-D input, but
    # produces its own source-aware mention set.
    question_json = json.dumps(
        build_step1_input(question), ensure_ascii=False, separators=(",", ":")
    )
    s1_prompt = prompt_step1.replace("<<<<QUESTION_JSON>>>>", question_json)
    s1_started = time.perf_counter()
    extracted = _call_and_parse(
        adapter, STEP1_SYSTEM, s1_prompt, STEP1_SCHEMA, MAX_TOKENS_STEP1,
        lambda raw: parse_mention_payload(raw, question),
    )
    step1_runtime_ms = round((time.perf_counter() - s1_started) * 1000, 3)
    sub_claims = extracted["sub_claims"]

    matched_global: list[str] = []
    used_rels: list[str] = []
    entity_links: list[dict] = []
    relation_selections: list[dict] = []
    seed_by_id: dict[str, dict] = {}
    relations_by_node: dict[str, set[str]] = {}
    all_relations: set[str] = set()
    step2b_calls = 0
    step2b_parse_ok = 0
    step2b_runtime_ms = 0.0
    nodelink_calls = 0
    nodelink_runtime_ms = 0.0

    # ── Linking phase 1: resolve exact/alias now; flag the rest for the model.
    proposed_by_sc: dict[str, list[dict]] = {}
    pending: list[dict] = []
    for sc in sub_claims:
        recs = []
        for mention in sc["mentions"]:
            rec = linker.propose(
                qid=qid,
                mention=mention["text"],
                origin=mention["origin"],
                source_span=mention["source_span"],
            )
            recs.append(rec)
            if rec.get("needs_choice"):
                pending.append(rec)
        proposed_by_sc[sc["subclaim_id"]] = recs

    # ── Linking phase 2: one batched model node-linking call for this question.
    #    Non-exact mentions are decided by the same evaluated model choosing a
    #    node from a bounded candidate set, or null (fail closed).
    if pending:
        requests = [linker.choice_request(p) for p in pending]
        nl_prompt = build_nodelink_prompt(prompt_nodelink, requests)
        nl_started = time.perf_counter()
        decisions = _call_and_parse(
            adapter, NODELINK_SYSTEM, nl_prompt, NODELINK_SCHEMA, MAX_TOKENS_NODELINK,
            lambda raw: parse_node_choices(raw, requests),
        )
        nodelink_runtime_ms = round((time.perf_counter() - nl_started) * 1000, 3)
        nodelink_calls = 1
        for idx, p in enumerate(pending):
            p["_chosen"] = decisions.get(idx)

    # ── Linking phase 3: finalize every mention into a link record + seeds.
    matched_by_sc: dict[str, dict[str, dict]] = {}
    for sc in sub_claims:
        matched_by_id: dict[str, dict] = {}
        for rec in proposed_by_sc[sc["subclaim_id"]]:
            chosen = rec.pop("_chosen", None) if rec.get("needs_choice") else None
            link = linker.finalize_choice(rec, chosen)
            link["subclaim_id"] = sc["subclaim_id"]
            entity_links.append(link)
            if link["status"] in {"exact", "alias", "model_pick"}:
                node = dict(link["matched_node"] or {})
                node_id = node.get("element_id")
                if node_id:
                    node["id"] = node_id
                    matched_by_id[node_id] = node
                    seed = seed_by_id.setdefault(
                        node_id,
                        {
                            "element_id": node_id,
                            "seed_node_ids": [node_id],
                            "subclaim_ids": [],
                            "origins": [],
                            "link_statuses": [],
                        },
                    )
                    for field, value in (
                        ("subclaim_ids", sc["subclaim_id"]),
                        ("origins", link["origin"]),
                        ("link_statuses", link["status"]),
                    ):
                        if value not in seed[field]:
                            seed[field].append(value)
        matched_by_sc[sc["subclaim_id"]] = matched_by_id

    # Step 2a + 2b per sub-claim over the resolved nodes.  No model output is
    # allowed to bypass the linker or to fall back to arbitrary relation order.
    for sc in sub_claims:
        sentence = sc["text"]
        matched = list(matched_by_sc[sc["subclaim_id"]].values())
        if not matched:
            continue
        matched_global.extend(node["name"] for node in matched)
        for node in matched:
            relations_by_node.setdefault(node["id"], set())
        cands = relation_candidates(driver, [node["id"] for node in matched])
        if not cands:
            relation_selections.append(
                {
                    "subclaim_id": sc["subclaim_id"],
                    "candidate_relations": [],
                    "selected_relations": [],
                    "status": "no_graph_relations",
                    "decision_reason": "linked nodes have no adjacent graph relations",
                }
            )
            continue

        # The approved design calls Step 2b whenever there are candidates,
        # even when the candidate set is smaller than TOP_K_RELATIONS.
        s2_prompt = (prompt_step2
                     .replace("<<<<TOP_K>>>>", str(TOP_K_RELATIONS))
                     .replace("<<<<SENTENCE>>>>", sentence)
                     .replace(
                         "<<<<RELATION_SET>>>>",
                         json.dumps(cands, ensure_ascii=False),
                     ))
        s2_started = time.perf_counter()

        def _parse_step2b(raw: str) -> dict:
            return parse_relation_selection(raw, cands, max_relations=TOP_K_RELATIONS)

        try:
            selection = _call_and_parse(
                adapter, STEP2_SYSTEM, s2_prompt, STEP2_SCHEMA, MAX_TOKENS_STEP2,
                _parse_step2b,
            )
        except RelationSelectionError as exc:
            raise RelationSelectionError(
                f"{qid}/{sc['subclaim_id']}: {exc}"
            ) from exc
        step2b_runtime_ms += (time.perf_counter() - s2_started) * 1000
        step2b_calls += 1
        step2b_parse_ok += 1
        selection["subclaim_id"] = sc["subclaim_id"]
        relation_selections.append(selection)
        selected = selection["selected_relations"]
        used_rels.extend(selected)
        for node in matched:
            relations_by_node[node["id"]].update(selected)
        all_relations.update(selected)

    retrieval_started = time.perf_counter()
    expanded = expand_subgraph(
        list(seed_by_id.values()),
        sorted(all_relations),
        lambda node_ids, relations: neo4j_fetch_edges(driver, node_ids, relations),
        relations_by_node=relations_by_node,
        max_hops=MAX_HOP,
        max_triples_per_node=MAX_TRIPLES_PER_NODE,
        max_evidence_per_question=MAX_EVIDENCE_PER_QUESTION,
    )
    ranked = rank_and_budget_evidence(
        expanded["evidence"], max_per_origin=10, max_total=30
    )
    final = ranked["evidence"]
    retrieval_runtime_ms = round((time.perf_counter() - retrieval_started) * 1000, 3)
    prompt_evidence = [
        {"head": record["head"], "relation": record["relation"], "tail": record["tail"]}
        for record in final
    ]
    context_text = (
        "\n".join(
            f"{record['head']} --[{record['relation']}]--> {record['tail']}"
            for record in final
        )
        or "(無可靠三元組)"
    )

    return {
        "qid": qid,
        "sub_claims": sub_claims,
        "mentions": extracted["mentions"],
        "entity_links": entity_links,
        "relation_selections": relation_selections,
        "entities_matched": list(dict.fromkeys(matched_global)),
        "relations_used": list(dict.fromkeys(used_rels)),
        "evidence_audit": {
            "expansion": expanded,
            "ranking": ranked,
        },
        "n_evidence_pre_extractor": expanded["n_before_question_cap"],
        "n_evidence_kept": len(final),
        "subgraph": {
            "evidence": prompt_evidence,
        },
        "context_text": context_text,
        "n_nodes_kept": len(
            {record["head_id"] for record in final}
            | {record["tail_id"] for record in final}
        ),
        "n_edges_kept": len(final),
        "_step1_parse_ok": True,
        "_step2b_calls": step2b_calls,
        "_step2b_parse_ok": step2b_parse_ok,
        "_nodelink_calls": nodelink_calls,
        "metrics": {
            "model": adapter.name,
            "phase": "extractor",
            "question_runtime_ms": round((time.perf_counter() - question_started) * 1000, 3),
            "step1_runtime_ms": step1_runtime_ms,
            "step2b_runtime_ms": round(step2b_runtime_ms, 3),
            "nodelink_runtime_ms": round(nodelink_runtime_ms, 3),
            "retrieval_runtime_ms": retrieval_runtime_ms,
            "step1_calls": 1,
            "step2b_calls": step2b_calls,
            "nodelink_calls": nodelink_calls,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
        },
    }


# ─── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True,
                        choices=["phi", "e4b", "gptoss", "gptoss_groq", "gemma31b", "llama70b"])
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--aliases",
        type=Path,
        default=BACKEND_DIR / "exp_3" / "config" / "entity_aliases.json",
    )
    parser.add_argument(
        "--linker-config",
        type=Path,
        default=BACKEND_DIR / "exp_3" / "config" / "entity_linker_config.json",
    )
    parser.add_argument(
        "--embedding-cache",
        type=Path,
        default=BACKEND_DIR / "exp_3" / "cache" / "b4_semantic_index.json",
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--n_workers", type=int, default=0,
                        help="0 = 採模型預設")
    parser.add_argument("--limit", type=int, default=0,
                        help="僅跑前 N 題（smoke test 用），0=全跑")
    args = parser.parse_args()

    linker_config = json.loads(args.linker_config.read_text(encoding="utf-8"))
    # Route 2 (2026-07-12): no human threshold/margin calibration and no manual
    # alias approval.  Non-exact mentions are resolved by the evaluated model
    # choosing among embedding candidates (fail closed).  The freeze gate for
    # the formal heldout run is enforced by preflight_b4 --mode freeze, not here.

    adapter = build_adapter(args.model)
    n_workers = args.n_workers or MODEL_WORKERS.get(args.model, 2)
    print(f"[NF1] model={args.model}  adapter={adapter.name}  workers={n_workers}")
    print(f"  TOP_K={TOP_K_RELATIONS}  MAX_HOP={MAX_HOP}  temperature={TEMPERATURE}")

    prompt_step1 = load_prompt("exp_3/nf1_step1_sentence_divide_json_zh.txt")
    prompt_step2 = load_prompt("exp_3/nf1_step2_relation_retrieval_json_zh.txt")
    prompt_nodelink = load_prompt("exp_3/b4_node_linking.md")

    raw_qs = json.loads(args.questions.read_text(encoding="utf-8"))
    qs = normalize_question_set(raw_qs)
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
    embedding_model = linker_config.get("embedding_model") or DEFAULT_EMBEDDING_MODEL
    embedding_client = OpenAIEmbeddingClient(model=embedding_model)
    nodes = load_kg_nodes(driver)
    semantic_index = build_semantic_index(
        nodes,
        client=embedding_client,
        cache_path=args.embedding_cache,
    )
    linker = build_entity_linker(
        driver,
        args.aliases,
        args.linker_config,
        nodes=nodes,
        semantic_index=semantic_index,
        semantic_client=embedding_client,
    )
    print(f"  KG nodes indexed for linker: {len(linker.nodes)}")

    todo = [q for q in qs if q["qid"] not in done_map]
    print(f"  待處理: {len(todo)} 題")

    write_lock = threading.Lock()

    def _worker(q: dict):
        try:
            result = process_one_question(
                q, driver, adapter, linker, prompt_step1, prompt_step2,
                prompt_nodelink,
            )
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
                "metrics": {
                    "model": adapter.name,
                    "phase": "extractor",
                    "question_runtime_ms": None,
                    "step1_runtime_ms": None,
                    "step2b_runtime_ms": None,
                    "retrieval_runtime_ms": None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "cost_usd": None,
                },
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
