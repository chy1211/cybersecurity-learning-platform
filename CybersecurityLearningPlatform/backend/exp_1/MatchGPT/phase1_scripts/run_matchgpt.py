#!/usr/bin/env python3
"""
Phase 1 Step 1.4: MatchGPT Node Merging (Three Thresholds: 0.5 / 0.7 / 0.9)

流程：
  1. 從 Neo4j 載入所有 Post-validation 節點
  2. 計算 / 復用 embedding（LM Studio cache）
  3. Blocking：本體論類別分桶 + cosine ≥ 0.80 top-k=10
  4. LLM 判定（Llama-3.3-70b，6 key 並行，一次跑完所有候選對）
  5. 三組 threshold（0.5/0.7/0.9）各自：
       restore postvalidation_kg → 執行合併 → 取三層指標 → 備份
  6. 輸出 matchgpt_3layer_summary.json
"""

import csv
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
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
import torch
import torch.nn.functional as F
from neo4j import GraphDatabase
from openai import OpenAI

# 直接 import neo4j_backup_restore 函式（避免 subprocess stdin 問題）
sys.path.insert(0, str(Path(__file__).parent.parent))
import neo4j_backup_restore as _nbr

# ─── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
MATCHGPT_DIR = SCRIPT_DIR.parent
BACKEND_DIR  = MATCHGPT_DIR.parents[1]
ETL_DIR      = BACKEND_DIR / "ETL_module"
RESULTS_DIR  = MATCHGPT_DIR / "phase1_results"
BACKUPS_DIR  = MATCHGPT_DIR / "phase1_backups"
POSTVAL_BACKUP = BACKUPS_DIR / "postvalidation_kg.json"
EMBEDDING_CACHE_FILE = ETL_DIR / "embedding_cache.json"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompts import load_prompt

MATCHGPT_SYSTEM_PROMPT = load_prompt("matchgpt/merge_nodes_system.md")
MATCHGPT_USER_PROMPT = load_prompt("matchgpt/merge_nodes_user.md")

# ─── Neo4j ───────────────────────────────────────────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")

# ─── LLM API（6 把 NVIDIA key）────────────────────────────────────────────────
_RAW_KEYS = [
    "",
    "",
    "",
    "",
    "",
    "",
]
API_KEYS = [
    os.getenv(f"NVIDIA_API_KEY_{i+1}", k)
    for i, k in enumerate(_RAW_KEYS)
    if k.strip()
]
LLAMA_MODEL = "meta/llama-3.3-70b-instruct"
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"

LLAMA_CLIENTS = [
    OpenAI(base_url=NVIDIA_BASE, api_key=k) for k in API_KEYS
]
client_queue: queue.Queue = queue.Queue()
for c in LLAMA_CLIENTS:
    client_queue.put(c)

# ─── Embedding（LM Studio）────────────────────────────────────────────────────
EMBED_URL   = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1") + "/embeddings"
EMBED_MODEL = "text-embedding-embeddinggemma-300m-qat"
EMBED_TIMEOUT = 30

# ─── 本體論 15 類實體（與 03_validate_and_import_fixed.py 一致）─────────────────
ENTITY_TYPES = [
    "feature", "function", "attack", "vulnerability", "technique", "data",
    "principle", "risk", "tool", "system", "app", "policy", "attacker",
    "securityTeam", "user"
]

# ─── 超參數 ───────────────────────────────────────────────────────────────────
EMBED_SIM_THRESHOLD = 0.80   # blocking cosine 下限
TOP_K               = 10     # 每節點最多取幾個候選
THRESHOLDS          = [0.5, 0.7, 0.9]
LLM_WORKERS         = len(LLAMA_CLIENTS)  # 並行執行緒數 = key 數
LLM_BATCH_REPORT    = 50    # 每跑幾筆印一次進度

# ═══════════════════════════════════════════════════════════════════════════════
# Embedding
# ═══════════════════════════════════════════════════════════════════════════════

embedding_cache: dict = {}
embed_cache_lock = threading.Lock()

def load_embedding_cache():
    global embedding_cache
    if EMBEDDING_CACHE_FILE.exists():
        with open(EMBEDDING_CACHE_FILE, encoding="utf-8") as f:
            embedding_cache = json.load(f)
        print(f"  已載入 embedding 快取：{len(embedding_cache)} 筆")
    else:
        print("  embedding_cache.json 不存在，從空白開始")

def save_embedding_cache():
    with embed_cache_lock:
        with open(EMBEDDING_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(embedding_cache, f, ensure_ascii=False)

def get_embedding(text: str) -> list | None:
    with embed_cache_lock:
        if text in embedding_cache:
            return embedding_cache[text]

    # 嘗試呼叫 LM Studio
    for attempt in range(3):
        try:
            resp = requests.post(
                EMBED_URL,
                headers={"Content-Type": "application/json"},
                json={"model": EMBED_MODEL, "input": text},
                timeout=EMBED_TIMEOUT,
            )
            resp.raise_for_status()
            emb = resp.json()["data"][0]["embedding"]
            with embed_cache_lock:
                embedding_cache[text] = emb
            return emb
        except Exception as e:
            if attempt == 2:
                print(f"  [WARN] embedding 失敗（{text[:30]}...）：{e}")
                return None
            time.sleep(1 + attempt)
    return None


def cosine_sim(a: list, b: list) -> float:
    va = torch.tensor(a, dtype=torch.float32)
    vb = torch.tensor(b, dtype=torch.float32)
    return float(F.cosine_similarity(va.unsqueeze(0), vb.unsqueeze(0)).item())


# ═══════════════════════════════════════════════════════════════════════════════
# LLM 判定
# ═══════════════════════════════════════════════════════════════════════════════

ENTITY_TYPE_DEFS = {
    "feature":       "系統或工具的功能特性",
    "function":      "可執行之操作或功能",
    "attack":        "攻擊行為或攻擊手法",
    "vulnerability": "系統或軟體中的安全弱點",
    "technique":     "具體的技術方法或手段",
    "data":          "資訊或資料",
    "principle":     "資安原則或安全概念",
    "risk":          "潛在的安全風險",
    "tool":          "軟硬體工具",
    "system":        "資訊系統或基礎設施",
    "app":           "應用程式",
    "policy":        "安全政策或標準規範",
    "attacker":      "攻擊者或威脅行為者",
    "securityTeam":  "資安防禦團隊或角色",
    "user":          "一般使用者",
}

def build_matchgpt_prompt(name_a: str, type_a: str, name_b: str, type_b: str) -> str:
    type_def = ENTITY_TYPE_DEFS.get(type_a, type_a)
    return MATCHGPT_USER_PROMPT.format(
        type_a=type_a,
        type_def=type_def,
        name_a=name_a,
        name_b=name_b,
    )


def call_llama_once(prompt: str) -> dict | None:
    attempt = 0
    client = client_queue.get()  # 取得 Key，並扣留在該執行緒中直到成功或徹底失敗
    while True:
        try:
            completion = client.chat.completions.create(
                model=LLAMA_MODEL,
                messages=[
                    {"role": "system", "content": MATCHGPT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            client_queue.put(client)  # 成功後歸還 Key
            raw = completion.choices[0].message.content
            return json.loads(raw)
        except Exception as e:
            err = str(e).lower()
            attempt += 1
            wait = min(2 ** attempt, 60) + random.uniform(0, 2)
            
            if not ("429" in err or "rate limit" in err or "too many" in err):
                # 只有非限流的嚴重錯誤才印出，避免 429 洗版
                print(f"  [LLM Error] {e}  等待 {wait:.1f}s")
                
            time.sleep(wait)
            
            if attempt >= 8:
                print(f"  [SKIP] 超過重試上限，跳過此筆")
                client_queue.put(client)  # 徹底放棄時，歸還 Key 給下一個任務
                return None


def judge_one_pair(args) -> dict:
    idx, name_a, type_a, name_b, type_b, sim = args
    prompt = build_matchgpt_prompt(name_a, type_a, name_b, type_b)
    result = call_llama_once(prompt)
    if result is None:
        result = {"decision": "different", "confidence": 0.0, "reason": "API 失敗"}
    return {
        "idx":        idx,
        "name_a":     name_a, "type_a": type_a,
        "name_b":     name_b, "type_b": type_b,
        "similarity": round(sim, 4),
        "decision":   result.get("decision", "different"),
        "confidence": float(result.get("confidence", 0.0)),
        "reason":     result.get("reason", ""),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Neo4j 操作
# ═══════════════════════════════════════════════════════════════════════════════

def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))


def fetch_all_nodes(driver) -> list[dict]:
    with driver.session() as s:
        result = s.run("MATCH (n:Entity) RETURN n.name AS name, n.type AS type")
        return [{"name": r["name"], "type": r["type"]} for r in result]


def restore_postvalidation(wipe=True):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        _nbr.restore(driver, str(POSTVAL_BACKUP), wipe=wipe)
    finally:
        driver.close()


def execute_merges(driver, pairs_to_merge: list, pre_rel_count: int) -> dict:
    """執行 APOC mergeNodes，回傳合併統計。"""
    cross_type = 0
    merged_pairs = 0
    skipped = 0

    # properties: 'discard' → 保留第一個節點 (a) 的所有屬性（name 不變為 list）
    # mergeRels: true → 合併關係（去掉重複邊），可能產生自環會在後面統計
    MERGE_CYPHER = """
    MATCH (a:Entity {name: $name_a}), (b:Entity {name: $name_b})
    WITH a, b WHERE a.type = b.type
    CALL apoc.refactor.mergeNodes([a, b], {properties: 'discard', mergeRels: true})
    YIELD node
    RETURN node.name AS merged_name
    """

    with driver.session() as s:
        for p in pairs_to_merge:
            if p["type_a"] != p["type_b"]:
                cross_type += 1
                continue
            try:
                r = s.run(MERGE_CYPHER, name_a=p["name_a"], name_b=p["name_b"])
                rec = r.single()
                if rec:
                    merged_pairs += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  [WARN] merge 失敗 ({p['name_a']} / {p['name_b']}): {e}")
                skipped += 1

    # 計算自環（合併後可能產生）
    with driver.session() as s:
        self_loops = s.run(
            "MATCH (n)-[r]->(n) RETURN count(r) AS c"
        ).single()["c"]
        post_rel_count = s.run(
            "MATCH ()-[r]->() RETURN count(r) AS c"
        ).single()["c"]

    effective_rels = post_rel_count - self_loops
    preservation_rate = round(effective_rels / pre_rel_count, 4) if pre_rel_count else 1.0

    return {
        "merged_pairs":          merged_pairs,
        "skipped_pairs":         skipped,
        "cross_type_blocked":    cross_type,
        "cross_type_merge_rate": round(cross_type / len(pairs_to_merge), 4) if pairs_to_merge else 0.0,
        "self_loops_after":      self_loops,
        "post_rel_count":        post_rel_count,
        "relation_preservation_rate": preservation_rate,
    }


def compute_metrics(driver, label: str) -> dict:
    stats = {}
    with driver.session() as s:
        stats["node_count"] = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        stats["rel_count"]  = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        stats["isolated_node_count"] = s.run(
            "MATCH (n) WHERE NOT (n)--() RETURN count(n) AS c"
        ).single()["c"]
        stats["avg_degree"] = round(
            (2 * stats["rel_count"]) / stats["node_count"]
            if stats["node_count"] > 0 else 0.0, 4
        )

    gname_wcc = f"wcc_{label}"
    try:
        with driver.session() as s:
            s.run(f"CALL gds.graph.drop('{gname_wcc}', false)")
            s.run(f"CALL gds.graph.project('{gname_wcc}', 'Entity', "
                  f"{{RELATION: {{orientation: 'UNDIRECTED'}}}})")
            stats["wcc_count"] = s.run(
                f"CALL gds.wcc.stats('{gname_wcc}') YIELD componentCount"
            ).single()["componentCount"]
            s.run(f"CALL gds.graph.drop('{gname_wcc}', false)")
    except Exception as e:
        stats["wcc_count"] = f"ERROR: {e}"

    gname_lei = f"leiden_{label}"
    try:
        with driver.session() as s:
            s.run(f"CALL gds.graph.drop('{gname_lei}', false)")
            s.run(f"CALL gds.graph.project('{gname_lei}', 'Entity', "
                  f"{{RELATION: {{orientation: 'UNDIRECTED'}}}})")
            stats["leiden_modularity_gamma1"] = round(
                s.run(f"CALL gds.leiden.stats('{gname_lei}', {{gamma: 1.0}}) YIELD modularity"
                      ).single()["modularity"], 6
            )
            s.run(f"CALL gds.graph.drop('{gname_lei}', false)")
    except Exception as e:
        stats["leiden_modularity_gamma1"] = f"ERROR: {e}"

    return stats


def do_backup_and_copy(dest_path: Path):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(MATCHGPT_DIR / f"neo4j_backup_{timestamp}.json")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        _nbr.backup(driver, out_path)
    finally:
        driver.close()
    shutil.copy2(out_path, str(dest_path))
    print(f"  ✓ 備份 → {dest_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("Phase 1 Step 1.4: MatchGPT Node Merging")
    print("=" * 65)

    RESULTS_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)

    # ── 1. 確認 postvalidation_kg.json 存在 ─────────────────────────────────
    if not POSTVAL_BACKUP.exists():
        print(f"[ERROR] 找不到 {POSTVAL_BACKUP}，請先完成步驟 1.3")
        sys.exit(1)

    # ── 2. 載入 embedding 快取 ───────────────────────────────────────────────
    print("\n[1/5] 載入 embedding 快取...")
    load_embedding_cache()

    # ── 3. 從 Neo4j 取節點（當前應為 Post-validation 圖譜）──────────────────
    print("\n[2/5] 從 Neo4j 載入所有節點...")
    driver = get_driver()
    nodes = fetch_all_nodes(driver)
    driver.close()
    print(f"  節點數：{len(nodes)}")

    # ── 4. 計算 / 復用 embedding ─────────────────────────────────────────────
    print("\n[3/5] 計算 embedding（有快取則復用）...")
    name_to_emb: dict[str, list | None] = {}
    missing = [n for n in nodes if n["name"] not in embedding_cache]
    print(f"  快取命中：{len(nodes) - len(missing)}  需新算：{len(missing)}")

    if missing:
        print(f"  呼叫 LM Studio（{EMBED_URL}）...")
        for i, n in enumerate(missing, 1):
            emb = get_embedding(n["name"])
            name_to_emb[n["name"]] = emb
            if i % 100 == 0 or i == len(missing):
                print(f"  embedding 進度：{i}/{len(missing)}", end="\r")
        print()
        save_embedding_cache()
        print(f"  ✓ 快取已更新，共 {len(embedding_cache)} 筆")
    else:
        print("  全部命中快取，跳過 API 呼叫")

    for n in nodes:
        if n["name"] not in name_to_emb:
            name_to_emb[n["name"]] = embedding_cache.get(n["name"])

    # ── 5. Blocking：本體論分桶 + cosine ≥ 0.80 top-k=10 ────────────────────
    print("\n[4/5] 抽取候選節點對（type 分桶 + cosine blocking）...")
    candidate_pairs: list[tuple] = []  # (name_a, type_a, name_b, type_b, sim)

    by_type: dict[str, list] = {t: [] for t in ENTITY_TYPES}
    for n in nodes:
        t = n["type"]
        if t in by_type and name_to_emb.get(n["name"]) is not None:
            by_type[t].append(n)

    for etype, bucket in by_type.items():
        if len(bucket) < 2:
            continue
        names = [n["name"] for n in bucket]
        embs  = [name_to_emb[nm] for nm in names]

        # 批次化 cosine：一次算出所有對（PyTorch 矩陣運算，速度遠快於 nested loop）
        mat = torch.tensor(embs, dtype=torch.float32)           # (N, D)
        mat = F.normalize(mat, dim=1)                            # L2 norm
        sim_matrix = torch.mm(mat, mat.t())                      # (N, N)

        seen = set()
        N = len(names)
        for i in range(N):
            row = sim_matrix[i]
            for j in range(i + 1, N):
                sim_val = float(row[j].item())
                if sim_val >= EMBED_SIM_THRESHOLD:
                    key = (names[i], names[j])  # i < j，有序不重複
                    if key not in seen:
                        seen.add(key)
                        candidate_pairs.append((names[i], etype, names[j], etype, sim_val))

        # 若某節點候選超過 TOP_K，依 sim 降冪只保留最高的 TOP_K 個對
        # （重組：已按 i<j 順序加入，需對每個節點重新篩）
        if candidate_pairs:
            from collections import defaultdict
            node_cnt: dict[str, int] = defaultdict(int)
            filtered = []
            # 只針對此 etype 的對重新篩選（取本輪新加入的）
            # 使用 seen set 已去重，直接對此 bucket 結果按 sim 降冪再 top-k
            bucket_pairs = [(a, et_a, b, et_b, s) for (a, et_a, b, et_b, s) in candidate_pairs
                            if et_a == etype]
            candidate_pairs = [p for p in candidate_pairs if p[1] != etype]
            bucket_pairs.sort(key=lambda x: x[4], reverse=True)
            for p in bucket_pairs:
                a, _, b, _, _ = p
                if node_cnt[a] < TOP_K and node_cnt[b] < TOP_K:
                    filtered.append(p)
                    node_cnt[a] += 1
                    node_cnt[b] += 1
            candidate_pairs.extend(filtered)

    print(f"  候選對數：{len(candidate_pairs)}")

    # 儲存候選清單
    cand_path = RESULTS_DIR / "matchgpt_candidate_pairs.csv"
    with open(cand_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name_a", "type_a", "name_b", "type_b", "similarity"])
        for row in candidate_pairs:
            writer.writerow(row)
    print(f"  ✓ 候選清單 → {cand_path}")

    # ── 6. LLM 判定（6 key 並行，一次跑完所有候選對）────────────────────────
    print(f"\n[5/5] LLM 判定（{len(candidate_pairs)} 對，{LLM_WORKERS} 執行緒）...")

    tasks = [
        (i, name_a, type_a, name_b, type_b, sim)
        for i, (name_a, type_a, name_b, type_b, sim) in enumerate(candidate_pairs)
    ]

    decisions: list[dict] = [None] * len(tasks)
    
    # 建立輸出檔案，並寫入標頭 (Progressive saving - 避免中斷遺失資料)
    dec_path = RESULTS_DIR / "matchgpt_decisions.csv"
    with open(dec_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name_a", "type_a", "name_b", "type_b", "similarity",
                         "decision", "confidence", "reason"])

    from tqdm import tqdm
    import threading
    write_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=LLM_WORKERS) as executor:
        future_to_idx = {executor.submit(judge_one_pair, t): t[0] for t in tasks}
        
        # 使用 tqdm 顯示進度條
        for future in tqdm(as_completed(future_to_idx), total=len(tasks), desc="  LLM 判定進度"):
            result = future.result()
            decisions[result["idx"]] = result
            
            # 即時寫入 CSV (加上 Lock 避免多線程寫入衝突)
            if result:
                with write_lock:
                    with open(dec_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            result["name_a"], result["type_a"], result["name_b"], result["type_b"],
                            result["similarity"], result["decision"], result["confidence"], result["reason"]
                        ])

    print()
    print(f"  ✓ 判定結果即時寫入完成 → {dec_path}")

    same_total = sum(1 for d in decisions if d and d["decision"] == "same")
    print(f"  判定 same：{same_total} / {len(decisions)}")

    # ── 7. 讀取 Post-validation 基線指標 ─────────────────────────────────────
    # 從 JSON 取「原始 build」數字（用於論文三欄對比表）
    postval_stats_path = RESULTS_DIR / "post_validation_stats.json"
    with open(postval_stats_path, encoding="utf-8") as f:
        postval_stats = json.load(f)
    # 注：backup/restore 工具不保留同對節點多條邊，恢復後關係數略少（~39）
    # 此處仍用原始 build 數字做節點縮減比基線（節點數不受影響）
    pre_node_count = postval_stats["node_count"]   # 3703，從 build 取（精確）

    # ── 8. 三組 threshold 各自 restore → 合併 → 指標 → 備份 ─────────────────
    all_threshold_metrics = {}

    for threshold in THRESHOLDS:
        tstr = str(threshold).replace(".", "")
        print(f"\n{'='*65}")
        print(f"Threshold = {threshold}")
        print(f"{'='*65}")

        # 篩選此 threshold 之待合併對
        pairs_to_merge = [
            d for d in decisions
            if d and d["decision"] == "same" and d["confidence"] >= threshold
        ]
        print(f"  待合併對數：{len(pairs_to_merge)}（confidence ≥ {threshold}）")

        # 儲存此 threshold 的待合併明細
        merged_detail_path = RESULTS_DIR / f"matchgpt_merged_t{tstr}.csv"
        with open(merged_detail_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["name_a", "type_a", "name_b", "type_b",
                             "similarity", "confidence", "reason"])
            for p in pairs_to_merge:
                writer.writerow([p["name_a"], p["type_a"], p["name_b"], p["type_b"],
                                 p["similarity"], p["confidence"], p["reason"]])
        print(f"  ✓ 合併明細 → {merged_detail_path}")

        # Restore postvalidation 圖譜
        print("  Restore postvalidation_kg.json...")
        restore_postvalidation(wipe=True)

        # 從 DB 取還原後的實際關係數（用於 relation_preservation_rate）
        driver = get_driver()
        with driver.session() as s:
            pre_rel_count = s.run(
                "MATCH ()-[r]->() RETURN count(r) AS c"
            ).single()["c"]
        driver.close()
        print(f"  還原後基線：節點 {pre_node_count}，關係 {pre_rel_count}")

        # 執行合併
        driver = get_driver()
        print(f"  執行 APOC mergeNodes...")
        merge_stats = execute_merges(driver, pairs_to_merge, pre_rel_count)
        print(f"  合併完成：{merge_stats['merged_pairs']} 對，"
              f"跨類別攔截：{merge_stats['cross_type_blocked']} 對")

        # 計算指標
        print("  計算結構指標...")
        post_metrics = compute_metrics(driver, f"t{tstr}")
        driver.close()

        node_reduction = pre_node_count - post_metrics["node_count"]
        node_reduction_ratio = round(node_reduction / pre_node_count, 4) if pre_node_count else 0.0

        metrics = {
            "threshold": threshold,
            "timestamp": datetime.now().isoformat(),
            "pre_merge": {
                "node_count": pre_node_count,
                "rel_count":  pre_rel_count,
            },
            "post_merge": post_metrics,
            "merge_stats": {
                **merge_stats,
                "pairs_filtered": len(pairs_to_merge),
                "node_reduction":       node_reduction,
                "node_reduction_ratio": node_reduction_ratio,
            },
        }

        metrics_path = RESULTS_DIR / f"matchgpt_t{tstr}_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 指標 → {metrics_path}")
        print(f"  節點：{pre_node_count} → {post_metrics['node_count']}（縮減 {node_reduction_ratio*100:.1f}%）")
        print(f"  WCC：{post_metrics.get('wcc_count')}  "
              f"Modularity：{post_metrics.get('leiden_modularity_gamma1')}  "
              f"關係保留率：{merge_stats['relation_preservation_rate']}")

        # 備份
        dest = BACKUPS_DIR / f"postmatchgpt_t{tstr}.json"
        do_backup_and_copy(dest)
        all_threshold_metrics[str(threshold)] = metrics

    # ── 9. 三層指標彙整 ───────────────────────────────────────────────────────
    print("\n彙整三層指標總表...")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "pre_validation_baseline": {
            "node_count": postval_stats["node_count"],
            "rel_count":  postval_stats["rel_count"],
            "wcc_count":  postval_stats.get("wcc_count"),
            "leiden_modularity_gamma1": postval_stats.get("leiden_modularity_gamma1"),
        },
        "layer1_structural": {},
        "layer2_ontology_consistency": {},
        "layer3_parameter_sensitivity": {},
    }

    for t in THRESHOLDS:
        tstr = str(t).replace(".", "")
        m = all_threshold_metrics[str(t)]
        pm = m["post_merge"]
        ms = m["merge_stats"]
        summary["layer1_structural"][f"t{t}"] = {
            "node_count":           pm["node_count"],
            "rel_count":            pm["rel_count"],
            "wcc_count":            pm.get("wcc_count"),
            "avg_degree":           pm.get("avg_degree"),
            "leiden_modularity":    pm.get("leiden_modularity_gamma1"),
            "node_reduction_ratio": ms["node_reduction_ratio"],
        }
        summary["layer2_ontology_consistency"][f"t{t}"] = {
            "pairs_filtered":           ms["pairs_filtered"],
            "merged_pairs":             ms["merged_pairs"],
            "cross_type_merge_rate":    ms["cross_type_merge_rate"],
            "relation_preservation_rate": ms["relation_preservation_rate"],
        }

    # 參數敏感性：相鄰 threshold 間的差值
    tkeys = [str(t) for t in THRESHOLDS]
    for i in range(len(tkeys) - 1):
        ta, tb = tkeys[i], tkeys[i+1]
        ma = all_threshold_metrics[ta]["post_merge"]
        mb = all_threshold_metrics[tb]["post_merge"]
        label = f"t{ta}_vs_t{tb}"
        summary["layer3_parameter_sensitivity"][label] = {
            "node_count_diff":     ma["node_count"] - mb["node_count"],
            "wcc_count_diff":      (ma.get("wcc_count") or 0) - (mb.get("wcc_count") or 0),
            "modularity_diff":     round(
                (ma.get("leiden_modularity_gamma1") or 0) -
                (mb.get("leiden_modularity_gamma1") or 0), 6
            ),
        }

    summary_path = RESULTS_DIR / "matchgpt_3layer_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"✓ 三層指標彙整 → {summary_path}")

    print("\n✅ 步驟 1.4 完成！")
    print("   候選對：", cand_path)
    print("   判定結果：", dec_path)
    print("   各 threshold 指標：", RESULTS_DIR)
    print("   三層彙整：", summary_path)


if __name__ == "__main__":
    main()


