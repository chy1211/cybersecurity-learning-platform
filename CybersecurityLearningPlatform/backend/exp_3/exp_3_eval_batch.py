#!/usr/bin/env python3
"""實驗 3 評估跑批：4 模型 × 2 條件 × 329 題 = 2,632 推理。

設計細節（D4-Q1~Q12 拍板於 2026-05-22；F1 定稿 2026-05-22）：
- 純 LLM / Graph RAG 兩條件，皆告知模型題型（單選/複選）
- JSON schema 強制（answer + reasoning）
- 答案標準化：去符號、大寫、字母排序、嚴格匹配
- 4 模型並行（4 endpoints 互不衝突）
- per-model checkpoint（resume）
- 先全跑 A 再全跑 B
- timeout 30s、429 backoff、max 4 retries
- reasoning ≤ 500 字
- JSON 解析失敗→regex fallback→parse_error

F1：top_k=10 + 6 KG-GPT few-shot（對齊 KG-GPT verify_claim_with_evidence.txt）
"""

from __future__ import annotations

import argparse
import json
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
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompts import load_prompt

# ─── 共用 schema / prompt ─────────────────────────────────────────────────────
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "pattern": "^[A-D]{1,4}$",
            "description": "答案字母組合（單選一個、複選多個按字母順序），例：'A' 或 'BCD'",
        },
        "reasoning": {
            "type": "string",
            "minLength": 5,
            "maxLength": 500,
            "description": "作答理由（中文，≤150 字）",
        },
    },
    "required": ["answer", "reasoning"],
    "additionalProperties": False,
}


_FEWSHOT_LLM_ONLY = load_prompt("exp_3/llm_only_fewshot.md")

# 6 範例 few-shot，對齊 KG-GPT verify_claim_with_evidence.txt（Kim et al., 2023）
# 涵蓋：evidence 直接支持 / evidence 不全 / evidence 部分支持 / evidence 為空 ×2 / 流程序列
_FEWSHOT_GRAPH_RAG = load_prompt("exp_3/graph_rag_fewshot.md")
LLM_ONLY_SYSTEM_TEMPLATE = load_prompt("exp_3/eval_llm_only_system.md")
GRAPH_RAG_SYSTEM_TEMPLATE = load_prompt("exp_3/eval_graph_rag_system.md")
EVAL_USER_TEMPLATE = load_prompt("exp_3/eval_user.md")


def build_prompt(question: dict, condition: str, subgraph: dict | None) -> tuple[str, str]:
    """回傳 (system_msg, user_msg)."""
    is_single = bool(question.get("is_single", True))
    type_hint = "單選題" if is_single else "複選題（可選多個正確答案）"
    opts = question["options"]
    options_lines = "\n".join(f"({k}) {opts[k]}" for k in sorted(opts.keys()))

    if condition == "llm_only":
        system = LLM_ONLY_SYSTEM_TEMPLATE.format(
            fewshot=_FEWSHOT_LLM_ONLY,
            type_hint=type_hint,
        )
        user = EVAL_USER_TEMPLATE.format(
            stem=question['stem'],
            options=options_lines,
            evidence_block="",
        )
    elif condition == "graph_rag":
        # KG-GPT 風格 prompt（F1，2026-05-22）
        # 對齊 KG-GPT verify_claim_with_evidence.txt（Kim et al., 2023）
        # - evidence set 以三元組陣列形式呈現
        # - 以 evidence set 為主要依據；若為空或無關則依專業知識作答
        evidence_list = []
        if subgraph:
            sub = subgraph.get("subgraph", {})
            for e in sub.get("evidence", []):
                evidence_list.append([e.get("head"), e.get("relation"), e.get("tail")])
            # fallback：若沒 evidence 欄位則從 context_text 解析
            if not evidence_list and subgraph.get("context_text"):
                for line in subgraph["context_text"].splitlines():
                    m = re.match(r"^(.+?)\s*--\[(.+?)\]-->\s*(.+)$", line.strip())
                    if m:
                        evidence_list.append([m.group(1).strip(), m.group(2).strip(), m.group(3).strip()])
        evidence_str = str(evidence_list) if evidence_list else "[]"

        system = GRAPH_RAG_SYSTEM_TEMPLATE.format(
            fewshot=_FEWSHOT_GRAPH_RAG,
            type_hint=type_hint,
        )
        user = EVAL_USER_TEMPLATE.format(
            stem=question['stem'],
            options=options_lines,
            evidence_block=f"Evidence set：{evidence_str}\n",
        )
    else:
        raise ValueError(f"unknown condition: {condition}")
    return system, user


def normalize_answer(text: str) -> str:
    """'BCD ' → 'BCD'; 'cbd' → 'BCD'; 'B,C,D' → 'BCD'; ' bcde ' → 'BCD'."""
    if not text:
        return ""
    chars = sorted({c for c in str(text).upper() if c in "ABCD"})
    return "".join(chars)


def _try_parse_json(raw: str) -> dict | None:
    """嘗試多種策略解析 JSON。失敗返回 None。"""
    if not raw:
        return None
    # try 1: 直接
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # try 2: ```json``` 區塊
    m = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # try 3: 最外層 { ... }（greedy 對 nested object）
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def parse_json_response(raw: str) -> dict:
    """解析 JSON 回應，抽出 answer 與 reasoning。失敗時 regex fallback。"""
    if not raw:
        return {"answer": "", "reasoning": "", "_parse_error": "empty"}

    parsed = _try_parse_json(raw)
    if parsed is None or not isinstance(parsed, dict):
        # regex fallback：抓 answer
        m_ans = re.search(r'"?answer"?\s*[:：]\s*"([A-Da-d ,，、]+)"?', raw)
        if m_ans:
            return {
                "answer": m_ans.group(1),
                "reasoning": raw[:300],
                "_parse_error": "regex_fallback",
            }
        return {"answer": "", "reasoning": raw[:300], "_parse_error": "no_match"}

    return {
        "answer": str(parsed.get("answer", "")).strip(),
        "reasoning": str(parsed.get("reasoning", ""))[:500],
    }


# ─── Model Adapters ───────────────────────────────────────────────────────────
class BaseAdapter:
    name: str = "base"

    def call(self, system: str, user: str) -> dict:
        """回傳 {"answer", "reasoning", "raw", "_parse_error"?, "_api_error"?}."""
        raise NotImplementedError


class LMStudioAdapter(BaseAdapter):
    """LM Studio /v1/chat/completions （Phi-4-mini-reasoning / Llama-3.1-8B / Gemma-4-31B / gpt-oss-20b / e4b）."""

    def __init__(self, name: str, endpoint: str, model_id: str, max_tokens: int = 1024,
                 use_strict_schema: bool = True):
        self.name = name
        self.endpoint = endpoint
        self.model_id = model_id
        self.max_tokens = max_tokens
        # 2026-05-23: gpt-oss-20b GGUF + strict schema → 中文 reasoning 亂碼，故對 gpt-oss 關閉
        self.use_strict_schema = use_strict_schema

    def call(self, system: str, user: str) -> dict:
        import requests  # local
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.use_strict_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "exp82_answer",
                    "strict": True,
                    "schema": JSON_SCHEMA,
                },
            }
        attempt = 0
        last_err = None
        while attempt < 4:
            try:
                resp = requests.post(self.endpoint, headers={"Content-Type": "application/json"},
                                     json=payload, timeout=120)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"] or ""
                parsed = parse_json_response(content)
                parsed["raw"] = content[:1000]
                return parsed
            except Exception as e:
                last_err = str(e)[:200]
                attempt += 1
                wait = min(2 ** attempt, 30)
                if "429" in last_err.lower() or "rate" in last_err.lower():
                    time.sleep(wait)
                    continue
                if attempt >= 4:
                    break
                time.sleep(wait)
        return {"answer": "", "reasoning": "", "raw": "", "_api_error": last_err or "unknown"}


class GoogleAdapter(BaseAdapter):
    """Google GenAI SDK（保留作為 Gemma 備援；2026-05-22 改用本地 LM Studio）."""

    def __init__(self, name: str, api_key: str, model_id: str):
        self.name = name
        self.api_key = api_key
        self.model_id = model_id
        try:
            from google import genai  # noqa
            from google.genai import types  # noqa
        except ImportError as exc:
            raise RuntimeError("google-genai not installed; pip install google-genai") from exc
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def call(self, system: str, user: str) -> dict:
        from google.genai import types
        client = self._get_client()
        attempt = 0
        last_err = None
        while attempt < 4:
            try:
                resp = client.models.generate_content(
                    model=self.model_id,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0,
                        max_output_tokens=1024,
                    ),
                )
                content = (resp.text or "") if hasattr(resp, "text") else ""
                parsed = parse_json_response(content)
                parsed["raw"] = content[:1000]
                return parsed
            except Exception as e:
                last_err = str(e)[:200]
                attempt += 1
                wait = min(2 ** attempt, 30)
                if "429" in last_err.lower() or "rate" in last_err.lower():
                    time.sleep(wait)
                    continue
                if attempt >= 4:
                    break
                time.sleep(wait)
        return {"answer": "", "reasoning": "", "raw": "", "_api_error": last_err or "unknown"}


class GroqAdapter(BaseAdapter):
    """Groq OpenAI-compatible（gpt-oss-20b），多 key 並行池."""

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

    def call(self, system: str, user: str) -> dict:
        client = self._client_q.get()
        attempt = 0
        last_err = None
        try:
            while attempt < 5:
                try:
                    resp = client.chat.completions.create(
                        model=self.model_id,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.0,
                        max_tokens=1024,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "exp82_answer",
                                "strict": True,
                                "schema": JSON_SCHEMA,
                            },
                        },
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = parse_json_response(content)
                    parsed["raw"] = content[:1000]
                    return parsed
                except Exception as e:
                    last_err = str(e)[:200]
                    attempt += 1
                    wait = min(2 ** attempt, 30)
                    if "429" in last_err.lower() or "rate" in last_err.lower() or "tpm" in last_err.lower():
                        time.sleep(wait)
                        continue
                    if attempt >= 5:
                        break
                    time.sleep(wait)
        finally:
            self._client_q.put(client)
        return {"answer": "", "reasoning": "", "raw": "", "_api_error": last_err or "unknown"}


class NVIDIAAdapter(BaseAdapter):
    """NVIDIA API（Llama-3.3-70B），多 key 並行池."""

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
        return OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)

    def call(self, system: str, user: str) -> dict:
        client = self._client_q.get()
        attempt = 0
        last_err = None
        try:
            while attempt < 4:
                try:
                    resp = client.chat.completions.create(
                        model=self.model_id,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.0,
                        max_tokens=1024,
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = parse_json_response(content)
                    parsed["raw"] = content[:1000]
                    return parsed
                except Exception as e:
                    last_err = str(e)[:200]
                    attempt += 1
                    wait = min(2 ** attempt, 30)
                    if "429" in last_err.lower() or "rate" in last_err.lower():
                        time.sleep(wait)
                        continue
                    if attempt >= 4:
                        break
                    time.sleep(wait)
        finally:
            self._client_q.put(client)
        return {"answer": "", "reasoning": "", "raw": "", "_api_error": last_err or "unknown"}


# ─── Model registry ───────────────────────────────────────────────────────────
def build_adapter(model_key: str) -> BaseAdapter:
    if model_key == "phi":
        return LMStudioAdapter(
            name="phi-4-mini-reasoning",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions"),
            model_id="microsoft/phi-4-mini-reasoning",
            max_tokens=2048,  # reasoning model 需較多 token
        )
    if model_key == "llama8b":
        return LMStudioAdapter(
            name="llama-3.1-8b-instruct",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL_ALT", os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions")),
            model_id="meta-llama-3.1-8b-instruct",
            max_tokens=1024,
        )
    if model_key == "gemma":
        # 2026-05-22 改：Google GenAI 額度耗盡，改用本地 LM Studio @ .80
        return LMStudioAdapter(
            name="gemma-4-31b",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL_ALT", os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions")),
            model_id="google/gemma-4-31b",
            max_tokens=2048,  # Gemma 易跳針，給較多空間
        )
    if model_key == "e4b":
        return LMStudioAdapter(
            name="gemma-4-e4b-it",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions"),
            model_id="gemma-4-e4b-it",
            max_tokens=1024,
        )
    if model_key == "gemma31b":
        return LMStudioAdapter(
            name="gemma-4-31b",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL_ALT", os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions")),
            model_id="google/gemma-4-31b",
            max_tokens=2048,
        )
    if model_key == "gptoss":
        # 2026-05-23 改：Groq TPD 不足，改用本地 LM Studio @ .80
        # 注意：gpt-oss-20b GGUF + 中文 strict schema 會 decode 亂碼，故關 strict schema
        return LMStudioAdapter(
            name="gpt-oss-20b (local)",
            endpoint=os.getenv("LM_STUDIO_CHAT_URL_ALT", os.getenv("LM_STUDIO_CHAT_URL", "http://127.0.0.1:1234/v1/chat/completions")),
            model_id="openai/gpt-oss-20b",
            max_tokens=4096,  # reasoning model 需大量 thinking token
            use_strict_schema=False,
        )
    if model_key == "gptoss_groq":
        # 備援：Groq endpoint
        groq_keys = [
            os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY"),
            os.getenv("GROQ_API_KEY_2"),
        ]
        return GroqAdapter(name="gpt-oss-20b", api_keys=groq_keys, model_id="openai/gpt-oss-20b")
    if model_key == "llama70b":
        api_keys = [
            os.getenv("NVIDIA_API_KEY_1"),
            os.getenv("NVIDIA_API_KEY_2"),
            os.getenv("NVIDIA_API_KEY_3"),
            os.getenv("NVIDIA_API_KEY_4"),
            os.getenv("NVIDIA_API_KEY_5"),
            os.getenv("NVIDIA_API_KEY_6"),
        ]
        return NVIDIAAdapter(name="llama-3.3-70b-instruct", api_keys=api_keys,
                             model_id="meta/llama-3.3-70b-instruct")
    raise ValueError(f"unknown model: {model_key}")


# ─── Per-model worker ─────────────────────────────────────────────────────────
def run_one_model(
    model_key: str,
    questions: list[dict],
    subgraphs: dict,
    output_path: Path,
    n_workers: int = 1,
    conditions: list[str] | None = None,
):
    conditions = conditions or ["llm_only", "graph_rag"]
    adapter = build_adapter(model_key)
    print(f"[{model_key}] adapter={adapter.name}  conditions={conditions}")

    # resume
    done: dict = {}
    if output_path.exists():
        try:
            done = json.loads(output_path.read_text(encoding="utf-8"))
            n_records = sum(1 for q in done.values() for c in conditions if c in q)
            print(f"  [Resume] 已有 {n_records} 個 (qid, condition) 結果")
        except Exception:
            done = {}

    # 任務清單：先全部 llm_only 再 graph_rag（D4-Q8）
    tasks = []
    for cond in conditions:
        for q in questions:
            if done.get(q["qid"], {}).get(cond):
                continue
            tasks.append((cond, q))

    n_todo = len(tasks)
    print(f"  待處理: {n_todo} 個 (qid, condition)")
    if n_todo == 0:
        print(f"[{model_key}] 已完成全部任務，直接結算")
        return done

    write_lock = threading.Lock()
    counter = {"done": 0}

    def _worker(item):
        cond, q = item
        subgraph = subgraphs.get(q["qid"])
        system, user = build_prompt(q, cond, subgraph)
        result = adapter.call(system, user)
        raw_ans = result.get("answer", "")
        norm_ans = normalize_answer(raw_ans)
        gold_norm = normalize_answer(q["answer"])
        is_correct = (norm_ans == gold_norm) and (norm_ans != "")
        record = {
            "answer_raw": str(raw_ans)[:50],
            "answer_norm": norm_ans,
            "reasoning": (result.get("reasoning") or "")[:500],
            "correct": is_correct,
            "gold": q["answer"],
            "gold_norm": gold_norm,
            "is_single": q.get("is_single", True),
        }
        if "_parse_error" in result:
            record["_parse_error"] = result["_parse_error"]
        if "_api_error" in result:
            record["_api_error"] = result["_api_error"]

        with write_lock:
            done.setdefault(q["qid"], {})[cond] = record
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
            counter["done"] += 1
            if counter["done"] % 25 == 0 or counter["done"] == n_todo:
                # 即時 acc
                rows = []
                for qid, by_cond in done.items():
                    for c, r in by_cond.items():
                        rows.append((c, r["correct"]))
                acc_llm = sum(1 for c, ok in rows if c == "llm_only" and ok) / max(1, sum(1 for c, _ in rows if c == "llm_only"))
                acc_rag = sum(1 for c, ok in rows if c == "graph_rag" and ok) / max(1, sum(1 for c, _ in rows if c == "graph_rag"))
                print(f"  [{model_key}] {counter['done']}/{n_todo}  即時 Acc_LLM={acc_llm:.3f}  Acc_RAG={acc_rag:.3f}")
        return q["qid"], cond

    if n_workers == 1:
        for t in tasks:
            _worker(t)
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            list(pool.map(_worker, tasks))

    return done


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--subgraphs", type=str, required=True,
                        help="路徑；可含 {model} placeholder 用於 per-model subgraph")
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--output_suffix", default="",
                        help="輸出檔之後綴，例：'_NF1' → eval_e4b_NF1.json")
    parser.add_argument("--models", default="phi,llama8b,gemma,llama70b",
                        help="comma-separated: phi/llama8b/gemma/llama70b/e4b/gptoss/gemma31b")
    parser.add_argument("--conditions", default="llm_only,graph_rag")
    parser.add_argument("--parallel_models", action="store_true",
                        help="4 模型並行（4 個 endpoints 互不衝突，可同時跑）")
    parser.add_argument("--workers_per_model", type=int, default=0,
                        help="每模型內部並行；0 = 採模型預設")
    args = parser.parse_args()

    qs = json.loads(args.questions.read_text(encoding="utf-8"))
    per_model_subgraph = "{model}" in args.subgraphs
    shared_sub = None
    if not per_model_subgraph:
        shared_sub = json.loads(Path(args.subgraphs).read_text(encoding="utf-8"))
        print(f"題庫 {len(qs)} 題 / 共享子圖 {len(shared_sub)} 個")
    else:
        print(f"題庫 {len(qs)} 題 / per-model 子圖（路徑模板：{args.subgraphs}）")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    # per-model worker 預設（可被 --workers_per_model 強制覆寫；0 = 採模型預設）
    _MODEL_WORKER_DEFAULT = {
        "phi": 1,
        "llama8b": 1,
        "gemma": 2,
        "llama70b": 6,
        "e4b": 2,
        "gptoss": 2,
        "gemma31b": 2,
    }

    def _model_thread(m):
        out = args.output_dir / f"eval_{m}{args.output_suffix}.json"
        if args.workers_per_model and args.workers_per_model > 0:
            workers = args.workers_per_model
        else:
            workers = _MODEL_WORKER_DEFAULT.get(m, 1)
        # 載入該模型之 subgraph（per-model 或共享）
        if per_model_subgraph:
            sg_path = Path(args.subgraphs.replace("{model}", m))
            if not sg_path.exists():
                print(f"[{m}] [跳過] 子圖檔不存在: {sg_path}")
                return
            this_sub = json.loads(sg_path.read_text(encoding="utf-8"))
            print(f"[{m}] workers={workers} 子圖={len(this_sub)}")
        else:
            this_sub = shared_sub
            print(f"[{m}] workers={workers}")
        run_one_model(m, qs, this_sub, out, n_workers=workers, conditions=conditions)

    if args.parallel_models:
        threads = []
        for m in models:
            t = threading.Thread(target=_model_thread, args=(m,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
    else:
        for m in models:
            _model_thread(m)

    # 最終摘要
    print("\n========= 最終摘要 =========")
    for m in models:
        out = args.output_dir / f"eval_{m}{args.output_suffix}.json"
        if not out.exists():
            print(f"  {m}: 無輸出檔")
            continue
        d = json.loads(out.read_text(encoding="utf-8"))
        rows = []
        for qid, by_cond in d.items():
            for c, r in by_cond.items():
                rows.append((c, r["correct"], r["is_single"]))
        for cond in conditions:
            this = [(ok, sg) for c, ok, sg in rows if c == cond]
            if not this:
                continue
            n = len(this)
            acc_all = sum(1 for ok, _ in this if ok) / n
            singles = [(ok, sg) for ok, sg in this if sg]
            acc_single = (sum(1 for ok, _ in singles if ok) / len(singles)) if singles else float("nan")
            print(f"  {m:>10} | {cond:>10} | n={n:>3} | Acc_all={acc_all:.3f} | Acc_single={acc_single:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


