import json
import argparse
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
from datetime import datetime
from tqdm import tqdm
from openai import OpenAI
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
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
API_KEY_7 = os.getenv("NVIDIA_API_KEY_7")

API_KEYS = [
    os.getenv("NVIDIA_API_KEY_1", API_KEY_1),
    os.getenv("NVIDIA_API_KEY_2", API_KEY_2),
    os.getenv("NVIDIA_API_KEY_3", API_KEY_3),
    os.getenv("NVIDIA_API_KEY_4", API_KEY_4),
    os.getenv("NVIDIA_API_KEY_5", API_KEY_5),
    os.getenv("NVIDIA_API_KEY_6", API_KEY_6),
    os.getenv("NVIDIA_API_KEY_7", API_KEY_7)
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

LLAMA_MODEL_NAME = "meta/llama-3.1-70b-instruct"

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

# --- [F12] Neo4j 有界重試（bounded retry） ---
# Neo4j 為遠端主機，浮動 IP 斷線時 session.run 會立即 raise。對齊 F7 embedding
# 呼叫的既有模式：重試上限、遞增等待、超過上限才 raise，交由上層安全網接手
# （import 路徑→「Neo4j Import Error」reject；Step 2 讀取路徑→F6「Internal Error」reject）。
NEO4J_READ_RETRY_ATTEMPTS = 20   # 讀取呼叫，總等待約 7-8 分鐘（同 F7 embedding）
NEO4J_WRITE_RETRY_ATTEMPTS = 15  # 寫入於 step2_and_write_lock 鎖內執行，總等待約 5 分鐘

_NEO4J_TRANSIENT_KEYWORDS = (
    "connection", "refused", "reset", "timed out", "timeout", "unavailable",
    "defunct", "broken pipe", "socket", "routing", "failed to read", "failed to write",
)

def is_transient_neo4j_error(e):
    """僅連線層級的暫時性錯誤可重試；語法錯誤、資料錯誤等立即 raise、不得吞掉。"""
    if isinstance(e, (ServiceUnavailable, SessionExpired, TransientError)):
        return True
    if isinstance(e, OSError):  # ConnectionError / TimeoutError / socket 層皆為其子類
        return True
    msg = str(e).lower()
    return any(k in msg for k in _NEO4J_TRANSIENT_KEYWORDS)

def run_with_neo4j_retry(op, what="", max_attempts=NEO4J_READ_RETRY_ATTEMPTS):
    """op 為無參數 callable，必須把 session.run(...) 與結果消費（list()/single()/
    consume()）包成同一組——run 為 lazy，只包 run 不包消費會漏接斷線。"""
    attempt = 0
    while True:
        try:
            return op()
        except Exception as e:
            if not is_transient_neo4j_error(e):
                raise
            attempt += 1
            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Neo4j unreachable after {attempt} attempts ({what}): {e}"
                ) from e
            wait_time = min(attempt * 3, 30)
            print(f"  [Neo4j 重試] {what}: {type(e).__name__}，第 {attempt}/{max_attempts} 次失敗，{wait_time}s 後重試...")
            time.sleep(wait_time)

# --- 參數與日誌設定 ---
RAW_TRIPLES_DIR = "RawTriples"
VALIDATED_DIR = "Validated"
REJECTED_DIR = "Rejected"
ENABLE_API_REQUESTS_LOG = False
VALIDATE_SYSTEM_PROMPT = load_prompt("etl/validate_system.md")
VALIDATE_CLASS_PROPERTY_PROMPT = load_prompt("etl/validate_class_property.md")
VALIDATE_URI_STANDARDIZATION_PROMPT = load_prompt("etl/validate_uri_standardization.md")
VALIDATE_SEMANTIC_CONSISTENCY_PROMPT = load_prompt("etl/validate_semantic_consistency.md")

AUDIT_LOG_PATH = None
AUDIT_LOCK = threading.Lock()
AUDIT_WARNED_FAILURE = False


def default_audit_log_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join("logs", f"validation_audit_{timestamp}.jsonl")


def configure_audit_log(path=None):
    global AUDIT_LOG_PATH, AUDIT_WARNED_FAILURE
    AUDIT_LOG_PATH = os.fspath(path) if path else default_audit_log_path()
    AUDIT_WARNED_FAILURE = False
    return AUDIT_LOG_PATH


def classify_audit_stage(is_valid, triple):
    if is_valid:
        # [F8] accept 過去誤標 step3_semantic，混淆 stage 統計
        return "accepted"

    reason = str(triple.get("reject_reason") or "")
    if "Phase 1" in reason:
        return "phase1_schema"
    if "Step 1" in reason or "Class/Property" in reason:
        return "step1_class_property"
    if "Step 2" in reason or "URI" in reason:
        return "step2_uri"
    if "Step 3" in reason or "Semantic" in reason:
        return "step3_semantic"
    if "Neo4j Import Error" in reason:
        return "neo4j_import"
    return "other"


def summarize_reason(reason):
    text = str(reason or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:500]


def write_validation_audit(record):
    global AUDIT_WARNED_FAILURE
    if not AUDIT_LOG_PATH:
        return

    try:
        log_path = os.fspath(AUDIT_LOG_PATH)
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with AUDIT_LOCK:
            with open(log_path, "a", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, sort_keys=True)
                f.write("\n")
    except Exception:
        if not AUDIT_WARNED_FAILURE:
            print("[AUDIT_WARN] validation audit write failed; pipeline continues.")
            AUDIT_WARNED_FAILURE = True


def audit_validation_decision(is_valid, validated_triple, raw_triple, source_file="", source_index=None):
    reason = "" if is_valid else str(validated_triple.get("reject_reason") or "")
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "decision": "accept" if is_valid else "reject",
        "stage": classify_audit_stage(is_valid, validated_triple),
        "reason": reason,
        "reason_summary": "accepted" if is_valid else summarize_reason(reason),
        "source_file": source_file or str(raw_triple.get("source_file") or ""),
        "source_index": source_index if source_index is not None else raw_triple.get("source_index", ""),
        "raw_triple": raw_triple,
        "final_triple": validated_triple,
    }
    write_validation_audit(record)
    return record

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
    ("system", "generates", "data"), ("system", "uses", "data"), ("system", "has_a", "feature"), ("system", "connects_to", "system"), ("system", "has_a", "system"), ("system", "is_part_of", "system"), ("system", "has_a", "tool"),
    ("technique", "can_analyze", "app"), ("technique", "can_analyze", "data"), ("technique", "can_analyze", "system"), ("technique", "is_part_of", "technique"), ("technique", "has_a", "tool"),
    ("tool", "is_part_of", "app"), ("tool", "generates", "data"), ("tool", "has_a", "feature"), ("tool", "has_a", "function"), ("tool", "deployed_in", "system"), ("tool", "is_part_of", "system"), ("tool", "uses", "technique"), ("tool", "has_a", "tool"), ("tool", "is_part_of", "tool"),
    ("user", "uses", "app"), ("user", "uses", "data"), ("user", "implements", "policy"), ("user", "uses", "system"), ("user", "can_expose", "vulnerability"),

    # Attacker View
    ("app", "can_expose", "vulnerability"),
    ("attack", "is_part_of", "attack"), ("attack", "can_harm", "system"), ("attack", "can_harm", "app"), ("attack", "can_harm", "data"), ("attack", "violates", "principle"), ("attack", "depends_on", "tool"),
    ("attacker", "can_exploit", "vulnerability"), ("attacker", "uses", "feature"), ("attacker", "uses", "function"), ("attacker", "uses", "tool"), ("attacker", "uses", "technique"), ("attacker", "implements", "attack"), ("attacker", "can_harm", "app"), ("attacker", "can_harm", "data"), ("attacker", "can_harm", "system"), ("attacker", "controls", "system"), ("attacker", "connects_to", "system"),
    ("data", "can_expose", "vulnerability"),
    ("feature", "can_expose", "vulnerability"),
    ("system", "can_expose", "vulnerability"),
    ("technique", "implements", "attack"),
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
    "規則3：主體(Subject)類別若為 vulnerability (漏洞)，其身分為被動缺陷，原則上不可發起主動行為（如 can_analyze, implements, controls 等）。【特例允許】：可發起 'can_expose' (暴露) 動作。【僅檢查主體】：本規則只看主體類別；受體(Object)為 vulnerability 完全不觸發本規則（例：technique can_analyze vulnerability 為合法，不得引用本規則判違規）。",
    "規則4：principle (資安原則) 僅能作為被違反(violates)的受體(Object)，不可作為發起動作的主體(Subject)。",
    "規則5：僅當關係為 uses 且主體 (Subject) 的類別是 data 時，才違反本規則。【僅檢查主體】：主體類別不是 data 時本規則一律不觸發——即使受體 (Object) 是 data 也完全合法（例：system uses data、user uses data 皆為合法，不得引用本規則判違規）。",
    "規則6：當關係為 deployed_in (部署於) 時，受體 (Object) 的類別必須是 system (系統)。",
    "規則7：當關係為 generates (產生) 時，受體 (Object) 的類別必須是 data (資料)。",
    "規則8：當關係為 controls (控制) 時，主體 (Subject) 必須是具有主動執行能力的角色或工具（如 attacker, securityTeam, tool），不可是被動資料或特徵。"
]

# [F13] Step 3 語意規則機械複核 --------------------------------------------------
# Lsr 規則 2-8 的觸發條件皆為 (主體型別, 關係, 受體型別) 層級、可由程式判定；
# 且 ALLOWED_EDGES 98 條合法邊不含任何違規組合——進入 Step 3 的三元組已通過
# Step 2 的 schema 複檢，這些機械條件必然不成立。實測 LLM 會在逐字引用規則
# 後仍反向誤判（run2 前 38%：step3 拒絕 47 筆中 44 筆確認誤拒），故 LLM 判
# violation 時由程式逐條複核：機械條件皆不成立、且未引用規則 1（唯一非型別
# 層級、跨三元組的語意規則）者，判定為規則誤用之誤拒，改判通過並留存紀錄。
_RULE1_CITE_PAT = re.compile(r"規則\s*1(?!\d)")

def _cites_rule1(res_3):
    """規則 1 引用偵測：只看最終判定 reason（step_1_rule_matching 是規則引用
    工作區，舊版 prompt 會整段抄錄全部規則、含規則1 字樣，不可作為依據），
    另以「攻擊者/安全團隊雙雙出現」作為未寫規則編號時的保守備援。"""
    reason = str(res_3.get('reason', ''))
    if _RULE1_CITE_PAT.search(reason):
        return True
    return (('attacker' in reason or '攻擊者' in reason)
            and ('securityTeam' in reason or '安全團隊' in reason))

def step3_mechanical_recheck(t, res_3):
    """複核 Step 3 的 violation 判定；回傳 dict，override=True 表示翻案通過。"""
    s_type = t['subject'].get('type', '')
    o_type = t['object'].get('type', '')
    rel = t.get('relation', '')
    hits = []
    if rel == 'mitigates' and s_type not in ('policy', 'technique', 'tool'):
        hits.append('規則2')
    if s_type == 'vulnerability' and rel != 'can_expose':
        hits.append('規則3')
    if s_type == 'principle':
        hits.append('規則4')
    if s_type == 'data' and rel == 'uses':
        hits.append('規則5')
    if rel == 'deployed_in' and o_type != 'system':
        hits.append('規則6')
    if rel == 'generates' and o_type != 'data':
        hits.append('規則7')
    if rel == 'controls' and s_type in ('data', 'feature'):
        hits.append('規則8')
    cites_rule1 = _cites_rule1(res_3)
    return {
        'override': (not hits) and (not cites_rule1),
        'mechanical_hits': hits,
        'cites_rule1': cites_rule1,
        'llm_reason': str(res_3.get('reason', '')),
    }

# [修復 1: 確定性字串正規化，消除大小寫/空格造成的假冗餘節點]
def normalize_entity_name(name: str) -> str:
    """統一大小寫與首尾空白。原始名稱保留於 display_name，MERGE 以正規化名稱為鍵。"""
    return name.strip().lower()

def extract_json(text):
    # [F1] 解析順序修正：response_format=json_object 下頂層必為 object，
    # 先整段解析、再抓 dict、最後才抓 array；舊版先抓 `\[.*\]` 會把
    # 「含陣列欄位的合法 dict 回應」毀成陣列，導致 response 欄位遺失。
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    match_obj = re.search(r'\{.*\}', text, re.DOTALL)
    if match_obj:
        try:
            return json.loads(match_obj.group(0))
        except Exception:
            pass
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    print(f"JSON 解析錯誤，無法解析回應:\n{text}")
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
            # [F7] 重試上限：舊版無上限，embedding 端點斷線會令整批靜默卡死
            if attempt >= 20:
                raise RuntimeError(f"Embedding endpoint failed after {attempt} attempts: {e}")
            wait_time = min(attempt * 3, 30)
            time.sleep(wait_time)

def get_semantic_top_k(session, entity_name, entity_type, top_k=5):
    if not entity_type or not entity_name:
        return []

    label = "".join([c for c in entity_type if c.isalnum()])
    query = f"MATCH (n:{label}) RETURN DISTINCT n.name AS name"
    # [F12] run 為 lazy：把 run + 迭代取回包成同一組重試單位
    existing_names = run_with_neo4j_retry(
        lambda: [record["name"] for record in session.run(query) if record["name"]],
        what=f"get_semantic_top_k({label})",
    )

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
    # [F12] run + single() 包成同一組重試單位
    record = run_with_neo4j_retry(
        lambda: session.run(query, name=entity_name).single(),
        what="resolve_type_conflict",
    )
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
    # [F5] consume()：session.run 為 lazy，未消費結果會延遲到 session 關閉才執行，
    # 屆時已在鎖外，曾實測產生同名同 label 重複節點（寫入競態）。
    # [F12] 重試單位＝run().consume() 整組：任一半途失敗即整組重試，成功才返回、
    # 才離開 step2_and_write_lock，維持 F5 語意（consume 不得移出重試迴圈）。
    # 鎖內重試會令其他 worker 一起等鎖，屬預期行為（Neo4j 斷線時全員反正無法寫入），
    # 故上限採較短的 NEO4J_WRITE_RETRY_ATTEMPTS，避免斷線過久時卡死整個 pipeline。
    run_with_neo4j_retry(
        lambda: session.run(
            query,
            norm_s_name=norm_s_name,
            norm_o_name=norm_o_name,
            display_s_name=display_s_name,
            display_o_name=display_o_name,
            source_file=t.get('source_file', ''),
            source_id=t.get('source_id', ''),
            source_index=t.get('source_index', '')
        ).consume(),
        what="import_to_neo4j",
        max_attempts=NEO4J_WRITE_RETRY_ATTEMPTS,
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

    # [F3] 自我迴圈防線（raw 層）：正規化後主受體同名即拒絕
    if t['subject'].get('name') and t['subject']['name'] == t['object'].get('name'):
        t['reject_reason'] = "Phase 1 (Self-Loop Violation): subject == object after normalization."
        _advance_counter()
        return False, t

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
            # [F2] 僅在 LLM 明確判定 duplicate 時才套用標準名：
            # 舊版「居後判斷」會在 response=correct 卻殘留 standard_* 欄位時強行改名
            if isinstance(res_2, dict) and res_2.get("response") == "duplicate":
                std_sub = res_2.get("standard_subject")
                std_obj = res_2.get("standard_object")
        except Exception:
            pass

        # URI 標準化套用到本地 t（[F2] 標準名一律重新正規化，維持 MERGE 鍵一致性）
        if std_sub and std_sub.strip():
            t['subject']['name'] = normalize_entity_name(std_sub)
        if std_obj and std_obj.strip():
            t['object']['name'] = normalize_entity_name(std_obj)

        # [F3] 合併後自我迴圈防線：同義詞合併若使主受體同名（母類/子類誤合併
        # 的典型症狀），還原本次改名、保留原始名稱，不阻斷後續驗證。
        if (std_sub or std_obj) and t['subject']['name'] == t['object']['name']:
            t['subject']['name'] = s_name
            t['object']['name'] = o_name
            t.setdefault('validation_history', {})['step_2_selfloop_reverted'] = True

        # ── [F4] 型別覆寫/改名後之 schema 複檢 ─────────────────────────────
        # 對最終名稱重新對齊既有節點 label（避免同名跨 label 重複節點），
        # 再以最終 (type, relation, type) 複查 98 合法邊；不合法即拒絕，
        # 杜絕「原始合法、覆寫後違法」的邊繞過 Phase 1 進入圖庫。
        t['subject']['type'] = resolve_type_conflict(neo4j_session, t['subject']['name'], t['subject']['type'])
        t['object']['type'] = resolve_type_conflict(neo4j_session, t['object']['name'], t['object']['type'])
        final_sig = (t['subject']['type'], t['relation'], t['object']['type'])
        if final_sig not in ALLOWED_EDGES:
            t['reject_reason'] = (
                f"Step 2 (Post-standardization Schema Violation): "
                f"{final_sig[0]} -> {final_sig[1]} -> {final_sig[2]} "
                f"(original: {s_type} -> {rel} -> {o_type})"
            )
            t.setdefault('validation_history', {})['step_2'] = res_2
            step2_next_idx += 1
            step2_cond.notify_all()
            return False, t

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
            # [F13] 機械複核：規則 2-8 條件不成立且未涉規則 1 → 誤拒翻案通過
            recheck = step3_mechanical_recheck(t, res_3)
            if recheck['override']:
                t['validation_history']['step_3_recheck'] = recheck
            else:
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

def validate_audit_and_import_triple(t, neo4j_session, triple_idx, source_file=""):
    original_t = copy.deepcopy(t)
    try:
        is_valid, validated_t = validate_and_import_triple(t, neo4j_session, triple_idx)
    except Exception as e:
        # [F6] 例外安全網：未捕捉例外過去會讓三元組無聲消失（不進 Validated/
        # Rejected/audit），且 Step 2 順序計數器未推進會使整個 chunk 死鎖。
        is_valid = False
        validated_t = t if isinstance(t, dict) else {"subject": {}, "relation": "", "object": {}}
        validated_t['reject_reason'] = f"Internal Error: {type(e).__name__}: {e}"
        global step2_next_idx
        with step2_cond:
            while step2_next_idx < triple_idx:
                step2_cond.wait()
            if step2_next_idx == triple_idx:
                step2_next_idx += 1
                step2_cond.notify_all()
    validated_t['original_raw_triple'] = original_t
    audit_validation_decision(
        is_valid,
        validated_t,
        original_t,
        source_file=source_file,
        source_index=original_t.get('source_index', triple_idx),
    )
    return is_valid, validated_t

def get_raw_triple_files(raw_dir):
    files = []
    for root, _, filenames in os.walk(raw_dir):
        for f in filenames:
            if f.endswith('.json'):
                files.append(os.path.join(root, f))
    return files

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Validate RawTriples and import accepted triples into Neo4j.")
    parser.add_argument(
        "--audit-log",
        default=None,
        help="Validation audit jsonl path. Default: ETL_module/logs/validation_audit_{timestamp}.jsonl",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    audit_log_path = configure_audit_log(args.audit_log)
    print(f"[INFO] validation_audit_log={audit_log_path}")

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

    # [F5] 唯一性約束：杜絕 MERGE 競態產生同名同 label 重複節點（雙保險）
    with neo4j_driver.session() as constraint_session:
        for label in sorted(Lc_p["Classes"]):
            # [F12] 啟動時只跑一次，包較簡短的 5 次重試即可
            run_with_neo4j_retry(
                lambda label=label: constraint_session.run(
                    f"CREATE CONSTRAINT uniq_{label}_name IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.name IS UNIQUE"
                ).consume(),
                what=f"create_constraint({label})",
                max_attempts=5,
            )
    print("Neo4j 唯一性約束就緒（15 labels）。")

    # [F7] embedding 端點健檢：避免開跑後才因端點離線而卡死
    try:
        _probe = requests.post(
            os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1") + "/embeddings",
            headers={"Content-Type": "application/json"},
            json={"model": "text-embedding-embeddinggemma-300m-qat", "input": "healthcheck"},
            timeout=10,
        )
        _probe.raise_for_status()
        print("Embedding 端點健檢通過。")
    except Exception as e:
        print(f"[FATAL] Embedding 端點健檢失敗：{e}；請先啟動 LM Studio embedding 服務再重跑。")
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
            s_name = t.get('subject', {}).get('name', '')
            o_name = t.get('object', {}).get('name', '')
            s_type = t.get('subject', {}).get('type', '')
            o_type = t.get('object', {}).get('type', '')
            rel = t.get('relation', '')
            print(f"  [開始驗證 {idx+1}/{len(triples)}] ({s_name}({s_type}), {rel}, {o_name}({o_type})) ...")
            
            with neo4j_driver.session() as thread_session:
                is_valid, validated_t = validate_audit_and_import_triple(
                    t,
                    thread_session,
                    idx,
                    source_file=rel_path,
                )
            
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
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


