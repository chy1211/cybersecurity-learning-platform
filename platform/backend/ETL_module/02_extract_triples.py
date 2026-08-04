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
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompts import load_prompt

# --- Gemma-4-31B via Google GenAI，多金鑰輪替 ---
# 2026-07-06 使用者拍板改回直連 Google（9router 隧道有 ~126s Cloudflare 硬限、扛不住萃取重呼叫）。
# 使用者提供多把 Gemini 金鑰輪流呼叫以分散額度：成功即輪下一把（round-robin），
# 單把 quota/rate 輪替下一把，API_KEY_INVALID 標記為 dead 永久跳過。
def _load_gemma_keys():
    keys = []
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

GEMMA_API_KEYS = _load_gemma_keys()
if not GEMMA_API_KEYS:
    print("找不到任何 Gemini 金鑰（請設定 GEMINI_API_KEYS 或 GEMINI_API_KEY）。")
    exit(1)
GEMMA_CLIENTS = [genai.Client(api_key=_k) for _k in GEMMA_API_KEYS]
GEMMA_MODEL_NAME = "gemma-4-31b-it"
_key_cursor = {"i": 0}
_dead_keys = set()
_key_lock = threading.Lock()  # 保護 _key_cursor / _dead_keys（並行安全）

CHUNKS_DIR = "Chunks"
RAW_TRIPLES_DIR = "RawTriples"

SYSTEM_PROMPT = load_prompt("etl/extract_triples_system.md")
USER_PROMPT_TEMPLATE = load_prompt("etl/extract_triples_user.md")
QUESTION_USER_PROMPT_TEMPLATE = load_prompt("etl/extract_triples_user_question.md")
QUESTION_SOURCE_ID_PREFIX = "question_"

def is_question_chunk(chunk):
    return str(chunk.get("source_id", "")).startswith(QUESTION_SOURCE_ID_PREFIX)

def build_user_prompt(chunk):
    prompt_template = QUESTION_USER_PROMPT_TEMPLATE if is_question_chunk(chunk) else USER_PROMPT_TEMPLATE
    return prompt_template.format(chunk_text=chunk['text'])

def extract_json(text):
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        match_obj = re.search(r'\{.*\}', text, re.DOTALL)
        if match_obj:
            return json.loads(match_obj.group(0))
        return json.loads(text)
    except Exception as e:
        print(f"JSON 解析錯誤: {e}\n原始文字:\n{text}")
        return []

def _pick_key_idx():
    """並行安全：原子地取下一把存活金鑰的 index 並前移游標；全 dead 回 None。
    每次選擇即前移游標→並行的多執行緒會各拿到不同金鑰，天然分散到 6 把。"""
    n = len(GEMMA_CLIENTS)
    with _key_lock:
        start = _key_cursor["i"] % n
        for step in range(n):
            cand = (start + step) % n
            if cand not in _dead_keys:
                _key_cursor["i"] = (cand + 1) % n
                return cand
        return None

def call_gemma(prompt):
    # 直連 Google GenAI，多金鑰輪替（執行緒安全）；system_instruction＋thinking high＋temperature 0.1 沿用原方法。
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        thinking_config=types.ThinkingConfig(thinking_level="high"),
        temperature=0.1,
    )
    n = len(GEMMA_CLIENTS)
    last_err = None
    for _ in range(n * 3):
        idx = _pick_key_idx()
        if idx is None:
            raise RuntimeError(f"所有 Gemini 金鑰皆失效（API_KEY_INVALID）。last={last_err}")
        try:
            resp = GEMMA_CLIENTS[idx].models.generate_content(
                model=GEMMA_MODEL_NAME, contents=prompt, config=config)
            return resp.text
        except Exception as e:
            msg = str(e)
            last_err = msg[:200]
            if "API_KEY_INVALID" in msg or "API key not valid" in msg or "PERMISSION_DENIED" in msg:
                with _key_lock:
                    _dead_keys.add(idx)
                print(f"  -> key#{idx} invalid; dead={len(_dead_keys)}/{n}")
                continue
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower() or "rate limit" in msg.lower():
                print(f"  -> key#{idx} quota/rate; rotating")
                time.sleep(2)
                continue
            if any(c in msg for c in ("500", "502", "503", "504")):
                print(f"  -> transient {msg[:60]}; wait 5s")
                time.sleep(5)
                continue
            raise
    raise RuntimeError(f"Gemini 呼叫多次失敗。last={last_err}")

def get_chunk_files(chunks_dir):
    chunk_files = []
    for root, _, filenames in os.walk(chunks_dir):
        for f in filenames:
            if f.endswith('.json'):
                chunk_files.append(os.path.join(root, f))
    return chunk_files

def process_chunk(file_path, chunks_dir, raw_triples_dir):
    """處理單一 chunk（並行 worker）。回傳 (status, n_triples, info)。"""
    rel_path = os.path.relpath(file_path, chunks_dir)
    source_filename = os.path.dirname(rel_path)
    chunk_basename = os.path.basename(rel_path)
    output_folder = os.path.join(raw_triples_dir, source_filename)
    os.makedirs(output_folder, exist_ok=True)  # exist_ok=True → 並行建同資料夾安全
    output_file_path = os.path.join(output_folder, chunk_basename)
    if os.path.exists(output_file_path):
        return ("skip", 0, rel_path)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            chunk = json.load(f)
        triples = extract_json(call_gemma(build_user_prompt(chunk)))
        if not isinstance(triples, list):
            triples = []
        for idx, t in enumerate(triples):
            t['source_id'] = chunk['source_id']
            t['source_file'] = chunk['source_file']
            t['source_index'] = idx + 1
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(triples, f, ensure_ascii=False, indent=2)
        return ("ok", len(triples), rel_path)
    except Exception as e:
        return ("error", 0, f"{rel_path}: {e}")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    chunks_dir = CHUNKS_DIR if os.path.isabs(CHUNKS_DIR) else os.path.join(script_dir, CHUNKS_DIR)
    raw_dir = RAW_TRIPLES_DIR if os.path.isabs(RAW_TRIPLES_DIR) else os.path.join(script_dir, RAW_TRIPLES_DIR)

    if not os.path.exists(chunks_dir):
        print(f"找不到輸入資料夾: {chunks_dir}")
        return

    chunk_files = get_chunk_files(chunks_dir)
    # 並行度：GEMMA_WORKERS（預設 1＝序列，忠實原行為）；全量建議 6（= 金鑰數，每 worker 天然佔一把）。
    workers = max(1, int(os.getenv("GEMMA_WORKERS", "1")))
    workers = min(workers, max(1, len(chunk_files)))
    print(f"\n開始進行萃取 (總共 {len(chunk_files)} 個區塊檔案，workers={workers}，模型={GEMMA_MODEL_NAME})...")

    total_triples = 0
    n_ok = n_skip = n_err = 0
    total = len(chunk_files)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_chunk, fp, chunks_dir, raw_dir): fp for fp in chunk_files}
        for done, fut in enumerate(as_completed(futures), start=1):
            status, n, info = fut.result()
            if status == "ok":
                total_triples += n
                n_ok += 1
                print(f"[{done}/{total}] ok   {info} ({n})")
            elif status == "skip":
                n_skip += 1
                print(f"[{done}/{total}] skip {info} (已存在)")
            else:
                n_err += 1
                print(f"[{done}/{total}] ERROR {info}")

    print("\n======================================")
    print(f"萃取完成！ok={n_ok} skip={n_skip} error={n_err}；總候選三元組 {total_triples} 筆。")
    print(f"結果儲存至: {raw_dir}")
    print("======================================")

if __name__ == "__main__":
    main()

