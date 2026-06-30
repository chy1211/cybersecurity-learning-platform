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
import logging
import queue
import threading
import concurrent.futures
import copy
import random
from tqdm import tqdm
from openai import OpenAI
from neo4j import GraphDatabase
import torch
import torch.nn.functional as F
import requests
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompts import load_prompt

# --- Llama API (NVIDIA) 設定 ---
API_KEY_1 = os.getenv("NVIDIA_API_KEY_1")
API_KEY_2 = os.getenv("NVIDIA_API_KEY_2")
API_KEY_3 = os.getenv("NVIDIA_API_KEY_3")
API_KEY_4 = os.getenv("NVIDIA_API_KEY_4")
API_KEY_5 = os.getenv("NVIDIA_API_KEY_5")
API_KEY_6 = os.getenv("NVIDIA_API_KEY_6")

API_KEYS = [
    os.getenv("NVIDIA_API_KEY_1", API_KEY_1),
    os.getenv("NVIDIA_API_KEY_2", API_KEY_2),
    os.getenv("NVIDIA_API_KEY_3", API_KEY_3),
    os.getenv("NVIDIA_API_KEY_4", API_KEY_4),
    os.getenv("NVIDIA_API_KEY_5", API_KEY_5),
    os.getenv("NVIDIA_API_KEY_6", API_KEY_6)
]
API_KEYS = [key.strip() for key in API_KEYS if key and key.strip()]

if not API_KEYS:
    print("請至少設定一組 NVIDIA API key")
    exit(1)

LLAMA_CLIENTS = []
for api_key in API_KEYS:
    try:
        LLAMA_CLIENTS.append(OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key))
    except Exception as e:
        print(f"初始化 Llama API Client 失敗。錯誤：{e}")
        exit(1)

LLAMA_MODEL_NAME = "meta/llama-3.3-70b-instruct"

# API 客戶端佇列 (Thread-safe)
client_queue = queue.Queue()
for client in LLAMA_CLIENTS:
    client_queue.put(client)

# 全域執行緒鎖：確保 Step 2 (查重) 與 Neo4j 寫入的原子性 (Atomicity)
step2_and_write_lock = threading.Lock()
# [Race Condition Fix] Condition 變數：強制 Step 2 依照 triple_idx 顺序執行
step2_cond     = threading.Condition(step2_and_write_lock)
step2_next_idx = 0  # 目前可進入 Step 2 的 idx，每個 chunk 開始前重置
# 批次內實體快取：讓同批次後續三元組的 Step 2 能看到已寫入的實體（受 step2_and_write_lock 保護）
session_entity_cache = {}  # {normalized_name: {"name": str, "type": str}}

# Embedding 本地快取：避免對相同文字重複呼叫 LM Studio
EMBEDDING_CACHE_FILE = "embedding_cache.json"
embedding_cache: dict = {}  # {text: [float, ...]}

def load_embedding_cache():
    global embedding_cache
    if os.path.exists(EMBEDDING_CACHE_FILE):
        try:
            with open(EMBEDDING_CACHE_FILE, 'r', encoding='utf-8') as f:
                embedding_cache = json.load(f)
            print(f"已載入 embedding 快取：{len(embedding_cache)} 筆")
        except Exception:
            embedding_cache = {}

def save_embedding_cache():
    try:
        with open(EMBEDDING_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(embedding_cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"儲存 embedding 快取失敗：{e}")


# --- Neo4j 設定 ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- 參數與日誌設定 ---
RAW_TRIPLES_DIR = "RawTriples"
VALIDATED_DIR = "Validated"
REJECTED_DIR = "Rejected"
ENABLE_API_REQUESTS_LOG = False
VALIDATE_SYSTEM_PROMPT = load_prompt("etl/validate_system.md")
VALIDATE_CLASS_PROPERTY_PROMPT = load_prompt("etl/validate_class_property.md")
VALIDATE_URI_STANDARDIZATION_PROMPT = load_prompt("etl/validate_uri_standardization.md")
VALIDATE_SEMANTIC_CONSISTENCY_PROMPT = load_prompt("etl/validate_semantic_consistency.md")

# 設定 API 請求日誌
api_logger = logging.getLogger("API_Requests")
if ENABLE_API_REQUESTS_LOG:
    api_logger.setLevel(logging.INFO)
    fh = logging.FileHandler("api_requests_log.txt", encoding="utf-8")
    formatter = logging.Formatter('%(asctime)s\n%(message)s\n' + '='*50 + '\n')
    fh.setFormatter(formatter)
    api_logger.addHandler(fh)
else:
    api_logger.addHandler(logging.NullHandler())

def log_api_call(step_name, prompt, response):
    if ENABLE_API_REQUESTS_LOG:
        api_logger.info(f"=== {step_name} ===\n[PROMPT]:\n{prompt}\n\n[RESPONSE]:\n{response}")

# --- 驗證資料集 ---
ALLOWED_EDGES = {
    # User View
    ("app", "generates", "data"), ("app", "uses", "data"), ("app", "has_a", "feature"), ("app", "connects_to", "system"), ("app", "depends_on", "system"), ("app", "deployed_in", "system"), ("app", "is_part_of", "system"), ("app", "has_a", "tool"),
    ("data", "deployed_in", "system"),
    ("feature", "uses", "data"), ("feature", "is_part_of", "tool"),
    ("function", "has_a", "feature"),
    ("system", "generates", "data"), ("system", "uses", "data"), ("system", "has_a", "feature"), ("system", "connects_to", "system"), ("system", "has_a", "system"), ("system", "has_a", "system"), ("system", "is_part_of", "system"), ("system", "is_part_of", "system"), ("system", "has_a", "tool"),
    ("technique", "can_analyze", "app"), ("technique", "can_analyze", "data"), ("technique", "can_analyze", "system"), ("technique", "is_part_of", "technique"), ("technique", "is_part_of", "technique"), ("technique", "has_a", "tool"),
    ("tool", "is_part_of", "app"), ("tool", "generates", "data"), ("tool", "has_a", "feature"), ("tool", "has_a", "function"), ("tool", "deployed_in", "system"), ("tool", "is_part_of", "system"), ("tool", "uses", "technique"), ("tool", "has_a", "tool"), ("tool", "is_part_of", "tool"),
    ("user", "uses", "app"), ("user", "uses", "data"), ("user", "implements", "policy"), ("user", "uses", "system"), ("user", "can_expose", "vulnerability"),

    # Attacker View
    ("app", "can_expose", "vulnerability"),
    ("attack", "is_part_of", "attack"), ("attack", "can_harm", "system"), ("attack", "can_harm", "app"), ("attack", "can_harm", "data"), ("attack", "violates", "principle"), ("attack", "depends_on", "tool"),
    ("attacker", "can_exploit", "vulnerability"), ("attacker", "uses", "feature"), ("attacker", "uses", "function"), ("attacker", "uses", "tool"), ("attacker", "uses", "technique"), ("attacker", "implements", "attack"), ("attacker", "can_harm", "app"), ("attacker", "can_harm", "data"), ("attacker", "can_harm", "system"), ("attacker", "controls", "system"), ("attacker", "connects_to", "system"),
    ("data", "can_expose", "vulnerability"),
    ("feature", "can_expose", "vulnerability"),
    ("system", "can_expose", "vulnerability"),
    ("technique", "implements", "attack"), ("technique", "depends_on", "tool"),
    ("tool", "controls", "system"),
    ("vulnerability", "can_expose", "risk"),

    # Security View
    ("feature", "can_analyze", "system"), ("feature", "can_analyze", "app"), ("feature", "can_analyze", "data"), ("feature", "can_analyze", "vulnerability"), ("feature", "can_detect", "attack"),
    ("function", "can_analyze", "vulnerability"), ("function", "can_analyze", "system"), ("function", "can_analyze", "app"), ("function", "can_analyze", "data"), ("function", "can_detect", "attack"),
    ("policy", "mitigates", "risk"), ("policy", "mitigates", "attack"),
    ("securityTeam", "can_analyze", "app"), ("securityTeam", "can_analyze", "data"), ("securityTeam", "can_analyze", "system"), ("securityTeam", "can_analyze", "feature"), ("securityTeam", "can_analyze", "attack"), ("securityTeam", "uses", "tool"), ("securityTeam", "uses", "technique"), ("securityTeam", "implements", "function"), ("securityTeam", "implements", "policy"), ("securityTeam", "can_detect", "vulnerability"), ("securityTeam", "controls", "system"), ("securityTeam", "controls", "tool"),
    ("technique", "can_analyze", "vulnerability"), ("technique", "can_detect", "attack"), ("technique", "mitigates", "attack"), ("technique", "depends_on", "tool"),
    ("tool", "can_analyze", "system"), ("tool", "can_analyze", "app"), ("tool", "can_analyze", "data"), ("tool", "can_analyze", "vulnerability"), ("tool", "can_analyze", "feature"), ("tool", "can_detect", "attack"), ("tool", "mitigates", "risk"), ("tool", "mitigates", "attack"), ("tool", "controls", "system")
}

Lc_p = {
    "Classes": [
        "feature", "function", "attack", "vulnerability", "technique", "data",
        "principle", "risk", "tool", "system", "app", "policy", "attacker",
        "securityTeam", "user"
    ],
    "Properties": [
        "has_a", "can_analyze", "can_expose", "can_exploit", "implements",
        "uses", "can_harm", "can_detect", "is_part_of", "mitigates", "violates",
        "deployed_in", "generates", "connects_to", "depends_on", "controls"
    ]
}

# [修復 2: 萃取邏輯與驗證規則的系統性衝突]
Lsr = [
    "規則1：同一實體不能同時具有攻擊者(attacker)與安全團隊(securityTeam)的身分。",
    "規則2：主體為 policy, technique 或 tool 時才可執行 mitigates 動作。",
    "規則3：主體類別若為 vulnerability (漏洞)，其身分為被動缺陷，原則上不可發起主動行為（如 can_analyze, implements, controls 等）。【特例允許】：可發起 'can_expose' (暴露) 動作。",
    "規則4：principle (資安原則) 僅能作為被違反(violates)的受體(Object)，不可作為發起動作的主體(Subject)。",
    "規則5：當關係為 uses 時，如果主體 (Subject) 的類別是 data，則為違反；但如果 data 僅是出現在受體 (Object) 位置，則屬合法。",
    "規則6：當關係為 deployed_in (部署於) 時，受體 (Object) 的類別必須是 system (系統)。",
    "規則7：當關係為 generates (產生) 時，受體 (Object) 的類別必須是 data (資料)。",
    "規則8：當關係為 controls (控制) 時，主體 (Subject) 必須是具有主動執行能力的角色或工具（如 attacker, securityTeam, tool），不可是被動資料或特徵。"
]

# [修復 1: 確定性字串正規化，消除大小寫/空格造成的假冗餘節點]
def normalize_entity_name(name: str) -> str:
    """統一大小寫與首尾空白。原始名稱保留於 display_name，MERGE 以正規化名稱為鍵。"""
    return name.strip().lower()

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

def call_llama(prompt):
    attempt = 0
    while True:
        client = client_queue.get()
        try:
            completion = client.chat.completions.create(
                model=LLAMA_MODEL_NAME,
                messages=[
                    {"role": "system", "content": VALIDATE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=8192,
                response_format={"type": "json_object"}
            )
            client_queue.put(client) # 成功後歸還
            return completion.choices[0].message.content
        except Exception as e:
            client_queue.put(client) # 無論如何先歸還到佇列最後面，讓它可以換下一個
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                print(f"  [API 429] 遇到 Rate Limit，馬上切換下一組 API Key 重試...")
                time.sleep(0.5) # 稍微喘息，避免全部 Key 都 429 時進入極速死迴圈
                continue
            else:
                attempt += 1
                wait_time = (2 ** min(attempt, 6)) + random.uniform(0, 3) # 最多等約 64 秒
                print(f"  [Llama API Error] {e}. Wait {wait_time:.2f}s...")
                time.sleep(wait_time)

def get_embedding_from_lmstudio(text):
    # 先查地端快取，有則直接返回不呼叫 API
    if text in embedding_cache:
        return embedding_cache[text]

    url = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1") + "/embeddings"
    headers = {"Content-Type": "application/json"}
    data = {
        "model": "text-embedding-embeddinggemma-300m-qat",
        "input": text
    }
    attempt = 0
    while True:
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            resp_json = response.json()
            embedding = resp_json['data'][0]['embedding']
            embedding_cache[text] = embedding  # 寫入快取
            return embedding
        except Exception as e:
            attempt += 1
            wait_time = attempt * 3
            time.sleep(wait_time)

def get_semantic_top_k(session, entity_name, entity_type, top_k=5):
    if not entity_type or not entity_name:
        return []

    label = "".join([c for c in entity_type if c.isalnum()])
    query = f"MATCH (n:{label}) RETURN DISTINCT n.name AS name"
    result = session.run(query)
    existing_names = [record["name"] for record in result if record["name"]]

    if not existing_names:
        return []

    query_vec = get_embedding_from_lmstudio(entity_name)
    corpus_vecs = [get_embedding_from_lmstudio(name) for name in existing_names]

    query_embedding = torch.tensor([query_vec])
    corpus_embeddings = torch.tensor(corpus_vecs)
    
    cos_scores = F.cosine_similarity(query_embedding, corpus_embeddings)

    k = min(top_k, len(existing_names))
    top_results = torch.topk(cos_scores, k=k)

    # [修復 2] 閾值從 0.3 提高至 0.80：減少 Ldr 雜訊，讓 Step 2 LLM 只看真正相似的候選
    top_entities = []
    for score, idx in zip(top_results[0], top_results[1]):
        if score.item() > 0.80:
            top_entities.append({
                "name": existing_names[idx.item()],
                "type": entity_type,
                "similarity_score": round(score.item(), 4)
            })
    return top_entities

def queryForDuplicateResources(session, s_name, s_type, o_name, o_type):
    Ldr_subject = get_semantic_top_k(session, s_name, s_type, top_k=10)
    Ldr_object = get_semantic_top_k(session, o_name, o_type, top_k=10)
    
    combined_Ldr = Ldr_subject + Ldr_object
    
    unique_Ldr = {}
    for item in combined_Ldr:
        if item['name'] not in unique_Ldr:
            unique_Ldr[item['name']] = item
            
    return list(unique_Ldr.values())

# [修復 4: 實體類別標註不穩定 (Type Instability)]
def resolve_type_conflict(session, entity_name, current_type):
    query = "MATCH (n) WHERE n.name = $name RETURN labels(n)[0] AS label LIMIT 1"
    result = session.run(query, name=entity_name)
    record = result.single()
    if record and record["label"]:
        return record["label"]
    return current_type

def import_to_neo4j(session, t):
    # MERGE 鍵：直接使用已經過 Phase 1 正規化 + Step 2 標準化的 name
    # （不再由 display_name 推算，避免 Step 2 標準化結果被覆蓋）
    norm_s_name = t['subject']['name']
    norm_o_name = t['object']['name']
    # display_name：用於 UI 顯示原始大小寫，fallback 為正規化名
    display_s_name = t['subject'].get('display_name', norm_s_name).strip()
    display_o_name = t['object'].get('display_name', norm_o_name).strip()
    s_type = t['subject']['type']
    relation = t['relation']
    o_type = t['object']['type']

    s_type_safe = "".join([c for c in s_type if c.isalnum()])
    o_type_safe = "".join([c for c in o_type if c.isalnum()])
    relation_safe = "".join([c for c in relation if c.isalnum() or c == '_'])

    query = f"""
    MERGE (s:{s_type_safe} {{name: $norm_s_name}})
    ON CREATE SET s.display_name = $display_s_name
    SET s.source_file = coalesce(s.source_file, []) + [$source_file],
        s.source_id = coalesce(s.source_id, []) + [$source_id],
        s.source_index = coalesce(s.source_index, []) + [$source_index]
    MERGE (o:{o_type_safe} {{name: $norm_o_name}})
    ON CREATE SET o.display_name = $display_o_name
    SET o.source_file = coalesce(o.source_file, []) + [$source_file],
        o.source_id = coalesce(o.source_id, []) + [$source_id],
        o.source_index = coalesce(o.source_index, []) + [$source_index]
    MERGE (s)-[r:{relation_safe}]->(o)
    SET r.source_file = coalesce(r.source_file, []) + [$source_file],
        r.source_id = coalesce(r.source_id, []) + [$source_id],
        r.source_index = coalesce(r.source_index, []) + [$source_index]
    """
    session.run(
        query,
        norm_s_name=norm_s_name,
        norm_o_name=norm_o_name,
        display_s_name=display_s_name,
        display_o_name=display_o_name,
        source_file=t.get('source_file', ''),
        source_id=t.get('source_id', ''),
        source_index=t.get('source_index', '')
    )

# [架構變更 5: 混合式過濾漏斗架構 (Hybrid Funnel Architecture)]
def validate_and_import_triple(t, neo4j_session, triple_idx):
    """
    Validate and import a triple into Neo4j using an optimized Hybrid Funnel Architecture.
    Reference: Regino & Reis (2025) "Can LLMs be Knowledge Graph Curators for Validating Triple Insertions?"
    triple_idx: 本三元組在當前 chunk 中的索引，用於 Step 2 強制順序執行。
    """
    
    # =========================================================================
    # Phase 1: Deterministic Syntactic & Schema Consistency (極速靜態檢查)
    # =========================================================================
    # 必须在任何早期返回前呼叫，保證 step2_next_idx 不會卡住後續執行緒
    def _advance_counter():
        global step2_next_idx
        with step2_cond:
            while step2_next_idx != triple_idx:
                step2_cond.wait()
            step2_next_idx += 1
            step2_cond.notify_all()

    if not isinstance(t, dict) or not all(k in t for k in ["subject", "relation", "object"]):
        t['reject_reason'] = "Phase 1 (Syntactic Violation - Optimized): Missing required components."
        _advance_counter()
        return False, t

    # [修復 1] 確定性正規化：在進入任何 LLM 驗證前，統一名稱格式
    # [修復 2] 保留原始大小寫供 LLM Prompt 顯示；MERGE 與 Ldr 查詢使用正規化版本
    # [修復 3] 正規化前先存入 display_name，確保 import_to_neo4j 拿到原始大小寫
    original_subject_display = t['subject'].get('name', '')
    original_object_display  = t['object'].get('name', '')
    t['subject']['display_name'] = original_subject_display.strip()  # strip 空白但保留大小寫
    t['object']['display_name']  = original_object_display.strip()
    if t['subject'].get('name'):
        t['subject']['name'] = normalize_entity_name(t['subject']['name'])
    if t['object'].get('name'):
        t['object']['name'] = normalize_entity_name(t['object']['name'])

    s_type = t['subject'].get('type', '')
    rel = t.get('relation', '')
    o_type = t['object'].get('type', '')

    if (s_type, rel, o_type) not in ALLOWED_EDGES:
        t['reject_reason'] = f"Phase 1 (Schema Edge Violation): {s_type} -> {rel} -> {o_type}"
        _advance_counter()
        return False, t

    # =========================================================================
    # Step 1 (論文對應): Class and Property Alignment
    # (無鎖，多執行緒並行)
    # =========================================================================
    prompt_1 = VALIDATE_CLASS_PROPERTY_PROMPT.format(
        subject_display=original_subject_display,
        subject_type=t['subject']['type'],
        relation=t['relation'],
        object_display=original_object_display,
        object_type=t['object']['type'],
        allowed_list=json.dumps(Lc_p, ensure_ascii=False, indent=2),
    )

    try:
        raw_res_1 = call_llama(prompt_1)
        res_1 = extract_json(raw_res_1)
        t.setdefault('validation_history', {})['step_1'] = res_1
        if isinstance(res_1, dict) and res_1.get("response") == "violation":
            t['reject_reason'] = f"Step 1 (Class/Property Violation): {res_1.get('reason')}"
            _advance_counter()
            return False, t
    except Exception as e:
        t['reject_reason'] = f"Step 1 LLM Error: {e}"
        _advance_counter()
        return False, t

    # =========================================================================
    # Step 2 (論文對應): URI Standardization
    # [Race Condition Fix] Lock 覆蓋 DB讀取 + LLM呼叫 + 預登錄 cache，確保原子性
    # Step 1 仍完全並行；Step 3 仍在鎖外並行；只有 Step 2 LLM 被序列化
    # =========================================================================
    s_name = t['subject']['name']
    o_name = t['object']['name']
    res_2 = None
    std_sub = None
    std_obj = None

    global step2_next_idx  # 需聲明 global，否則 += 賦值讓 Python 誤判為區域變數
    with step2_cond:
        # ── 強制順序：等待直到輪到自己的 triple_idx 才能進入 Step 2 ──────
        while step2_next_idx != triple_idx:
            step2_cond.wait()

        # ── DB 讀取 + 合併批次快取 ─────────────────────────────────────
        t['subject']['type'] = resolve_type_conflict(neo4j_session, s_name, s_type)
        t['object']['type'] = resolve_type_conflict(neo4j_session, o_name, o_type)
        Ldr_snapshot = queryForDuplicateResources(
            neo4j_session, s_name, t['subject']['type'], o_name, t['object']['type']
        )
        captured_s_type = t['subject']['type']
        captured_o_type = t['object']['type']
        existing_ldr_names = {e['name'] for e in Ldr_snapshot}
        for cached_name, cached_item in session_entity_cache.items():
            if cached_item['type'] in (captured_s_type, captured_o_type) and cached_name not in existing_ldr_names:
                Ldr_snapshot.append(cached_item)
                existing_ldr_names.add(cached_name)

        # ── Step 2 LLM（在鎖內，序列化確保原子性）──────────────────────────
        prompt_2 = VALIDATE_URI_STANDARDIZATION_PROMPT.format(
            subject_display=original_subject_display,
            subject_type=captured_s_type,
            object_display=original_object_display,
            object_type=captured_o_type,
            duplicate_resources=json.dumps(Ldr_snapshot, ensure_ascii=False, indent=2),
        )

        try:
            raw_res_2 = call_llama(prompt_2)
            res_2 = extract_json(raw_res_2)
            # 居後判斷：只要 LLM 填了 standard 就套用，不依賴 response 欄位
            # （防止 LLM 誤回 "correct" 卻已圖入同義詞）
            if isinstance(res_2, dict):
                if res_2.get("response") == "duplicate" or res_2.get("standard_subject") or res_2.get("standard_object"):
                    std_sub = res_2.get("standard_subject")
                    std_obj = res_2.get("standard_object")
        except Exception:
            pass

        # URI 標準化套用到本地 t
        if std_sub and std_sub.strip():
            t['subject']['name'] = std_sub
        if std_obj and std_obj.strip():
            t['object']['name'] = std_obj

        # ── 預登錄 session cache（在鎖內立即可見，消除 Race Condition）────────
        session_entity_cache[t['subject']['name']] = {"name": t['subject']['name'], "type": t['subject']['type']}
        session_entity_cache[t['object']['name']]  = {"name": t['object']['name'],  "type": t['object']['type']}

        # ── 順序計數器前進，通知等候中的下一個執行緒 ─────────────────────
        step2_next_idx += 1
        step2_cond.notify_all()
    # ── Step 2 完整原子性區段結束；鎖釋放 ──────────────────────────────────

    # =========================================================================
    # Step 3 (論文對應): Semantic Consistency
    # [步驟順序修復] 對應論文正確順序：Step1 → Step2(URI) → Step3(Semantic)
    # 在 URI 標準化之後才執行語義一致性，確保是對已去重的實體名稱做語義判斷。
    # (無鎖，多執行緒並行)
    # =========================================================================
    prompt_3 = VALIDATE_SEMANTIC_CONSISTENCY_PROMPT.format(
        subject_display=t['subject'].get('display_name', t['subject']['name']),
        subject_type=t['subject']['type'],
        relation=t['relation'],
        object_display=t['object'].get('display_name', t['object']['name']),
        object_type=t['object']['type'],
        semantic_rules=json.dumps(Lsr, ensure_ascii=False, indent=2),
    )

    try:
        raw_res_3 = call_llama(prompt_3)
        res_3 = extract_json(raw_res_3)
        t.setdefault('validation_history', {})['step_3'] = res_3
        if isinstance(res_3, dict) and res_3.get("response") == "violation":
            t['reject_reason'] = f"Step 3 (Semantic Violation): {res_3.get('reason')}"
            # Step 3 拒絕：移除 Step 2 預登錄的 cache 條目，避免汙染後續查詢
            with step2_and_write_lock:
                session_entity_cache.pop(t['subject']['name'], None)
                session_entity_cache.pop(t['object']['name'],  None)
            return False, t
    except Exception as e:
        t['reject_reason'] = f"Step 3 LLM Error: {e}"
        with step2_and_write_lock:
            session_entity_cache.pop(t['subject']['name'], None)
            session_entity_cache.pop(t['object']['name'],  None)
        return False, t

    # =========================================================================
    # Lock B：儲存驗證歷史 + 寫入 Neo4j（session cache 已在 Step 2 鎖內預登錄）
    # =========================================================================
    with step2_and_write_lock:
        t.setdefault('validation_history', {})['step_2'] = res_2
        try:
            import_to_neo4j(neo4j_session, t)
            return True, t
        except Exception as e:
            t['reject_reason'] = f"Neo4j Import Error: {e}"
            session_entity_cache.pop(t['subject']['name'], None)
            session_entity_cache.pop(t['object']['name'],  None)
            return False, t

def get_raw_triple_files(raw_dir):
    files = []
    for root, _, filenames in os.walk(raw_dir):
        for f in filenames:
            if f.endswith('.json'):
                files.append(os.path.join(root, f))
    return files

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if not os.path.exists(RAW_TRIPLES_DIR):
        print(f"找不到輸入資料夾: {os.path.abspath(RAW_TRIPLES_DIR)}")
        return

    raw_files = get_raw_triple_files(RAW_TRIPLES_DIR)

    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        neo4j_driver.verify_connectivity()
        print("Neo4j 連線成功。")
    except Exception as e:
        print(f"Neo4j 連線失敗: {e}")
        exit(1)

    print(f"\n開始驗證與寫入 (總共 {len(raw_files)} 個區塊檔案)...")
    load_embedding_cache()
    
    total_validated = 0
    total_rejected = 0

    for i, file_path in enumerate(tqdm(raw_files, desc="整體檔案處理進度", unit="file")):
        rel_path = os.path.relpath(file_path, RAW_TRIPLES_DIR)
        source_filename = os.path.dirname(rel_path)
        chunk_basename = os.path.basename(rel_path)
        
        validated_folder = os.path.join(VALIDATED_DIR, source_filename)
        rejected_folder = os.path.join(REJECTED_DIR, source_filename)
        os.makedirs(validated_folder, exist_ok=True)
        os.makedirs(rejected_folder, exist_ok=True)
        
        validated_file_path = os.path.join(validated_folder, chunk_basename)
        rejected_file_path = os.path.join(rejected_folder, chunk_basename)

        # [需求 1: 中斷接續] 只要 validated_file_path 存在即判定處理過，直接略過。
        if os.path.exists(validated_file_path):
            print(f"\n[{i+1}/{len(raw_files)}] 略過已處理檔案: {source_filename} -> {chunk_basename}")
            continue

        # [需求 3: 壞掉的 JSON 或空串列自動略過]
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                triples = json.load(f)
        except json.JSONDecodeError as e:
            print(f"\n[{i+1}/{len(raw_files)}] [警告] 檔案解析失敗 (JSON 格式錯誤)，略過: {chunk_basename}")
            continue
            
        if not isinstance(triples, list) or len(triples) == 0:
            print(f"\n[{i+1}/{len(raw_files)}] [提示] 檔案為空或格式不符，略過: {chunk_basename}")
            continue
            
        print(f"\n[{i+1}/{len(raw_files)}] 處理檔案: {source_filename} -> {chunk_basename} ({len(triples)} 筆)")
        
        chunk_validated = []
        chunk_rejected = []

        def process_triple(idx, t):
            # [需求 2: 保留最原始 Rawtriple 的資訊]
            original_t = copy.deepcopy(t)
            
            s_name = t.get('subject', {}).get('name', '')
            o_name = t.get('object', {}).get('name', '')
            s_type = t.get('subject', {}).get('type', '')
            o_type = t.get('object', {}).get('type', '')
            rel = t.get('relation', '')
            print(f"  [開始驗證 {idx+1}/{len(triples)}] ({s_name}({s_type}), {rel}, {o_name}({o_type})) ...")
            
            with neo4j_driver.session() as thread_session:
                is_valid, validated_t = validate_and_import_triple(t, thread_session, idx)
                
            # 將原始未修改的資訊存入驗證結果
            validated_t['original_raw_triple'] = original_t
            
            if is_valid:
                print(f"  ✅ [通過 {idx+1}/{len(triples)}] ({validated_t['subject']['name']}, {validated_t['relation']}, {validated_t['object']['name']})")
            else:
                reason = validated_t.get('reject_reason', 'Unknown reason')
                print(f"  ❌ [拒絕 {idx+1}/{len(triples)}] ({s_name}, {rel}, {o_name}) -> 原因: {reason}")
            
            return is_valid, validated_t

        # 每個 chunk 開始前重置批次快取與 Step 2 順序計數器
        global step2_next_idx
        session_entity_cache.clear()
        step2_next_idx = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_triple, idx, t) for idx, t in enumerate(triples)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    is_valid, validated_t = future.result()
                    if is_valid:
                        chunk_validated.append(validated_t)
                    else:
                        chunk_rejected.append(validated_t)
                except Exception as exc:
                    print(f"執行緒處理發生例外錯誤: {exc}")

        # 無論是否為空，必定產生輸出檔案，確保 [需求1] 可以依賴檔案存在性作為中斷點判斷。
        with open(validated_file_path, "w", encoding="utf-8") as f:
            json.dump(chunk_validated, f, ensure_ascii=False, indent=2)
            
        with open(rejected_file_path, "w", encoding="utf-8") as f:
            json.dump(chunk_rejected, f, ensure_ascii=False, indent=2)
            
        total_validated += len(chunk_validated)
        total_rejected += len(chunk_rejected)
        save_embedding_cache()  # 每個 chunk 完成後儲存快取

    neo4j_driver.close()
    print("\n======================================")
    print(f"驗證與匯入完成！")
    print(f"成功通過並寫入 Neo4j: {total_validated} 筆")
    print(f"被拒絕: {total_rejected} 筆")
    print("======================================")

if __name__ == "__main__":
    main()


