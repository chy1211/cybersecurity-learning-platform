#!/usr/bin/env python3
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
"""Step 1.4 前置測試：embedding server / APOC mergeNodes / LLM API"""
import json, requests, sys, queue, time
from pathlib import Path
from neo4j import GraphDatabase
from openai import OpenAI

NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")

EMBED_URL   = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1") + "/embeddings"
EMBED_MODEL = "text-embedding-embeddinggemma-300m-qat"

API_KEYS = [
    "",
    "",
]
LLAMA_MODEL = "meta/llama-3.3-70b-instruct"

MATCHGPT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = MATCHGPT_DIR.parents[1]
ETL_DIR = BACKEND_DIR / "ETL_module"
CACHE_FILE = ETL_DIR / "embedding_cache.json"

print("=" * 55)
print("Phase 1.4 前置確認")
print("=" * 55)

# 1. embedding cache
if CACHE_FILE.exists():
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)
    print(f"[OK] embedding_cache.json：{len(cache)} 筆")
else:
    print("[WARN] embedding_cache.json 不存在")
    cache = {}

# 2. LM Studio
print("\n[測試] LM Studio embedding server...")
try:
    r = requests.post(EMBED_URL,
        headers={"Content-Type": "application/json"},
        json={"model": EMBED_MODEL, "input": "防火牆"},
        timeout=10)
    r.raise_for_status()
    dim = len(r.json()["data"][0]["embedding"])
    print(f"[OK] LM Studio 可達，embedding 維度：{dim}")
    lm_ok = True
except Exception as e:
    print(f"[WARN] LM Studio 不可達：{e}")
    print(f"       將只使用快取（{len(cache)} 筆），無法算出快取外節點的 embedding")
    lm_ok = False

# 3. Neo4j + APOC mergeNodes
print("\n[測試] Neo4j APOC mergeNodes...")
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
try:
    with driver.session() as s:
        # 建臨時節點測試
        s.run("CREATE (:_TestMerge {name: '__test_a__', type: 'tool'})")
        s.run("CREATE (:_TestMerge {name: '__test_b__', type: 'tool'})")
        r = s.run("""
            MATCH (a:_TestMerge {name: '__test_a__'}), (b:_TestMerge {name: '__test_b__'})
            CALL apoc.refactor.mergeNodes([a, b], {properties: 'combine', mergeRels: true})
            YIELD node RETURN node.name AS n
        """).single()
        s.run("MATCH (n:_TestMerge) DETACH DELETE n")
    print(f"[OK] APOC mergeNodes 可用，合併結果節點：{r['n']}")
except Exception as e:
    print(f"[ERROR] APOC mergeNodes 失敗：{e}")
    driver.close()
    sys.exit(1)
driver.close()

# 4. 快取覆蓋率估算
print("\n[測試] Neo4j 節點 vs embedding 快取覆蓋率...")
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
with driver.session() as s:
    nodes = [r["name"] for r in s.run("MATCH (n:Entity) RETURN n.name AS name")]
driver.close()
covered = sum(1 for nm in nodes if nm in cache)
print(f"  Neo4j 節點：{len(nodes)}")
print(f"  快取命中：{covered}（{covered/len(nodes)*100:.1f}%）")
print(f"  需新算：{len(nodes)-covered}")
if not lm_ok and (len(nodes) - covered) > 0:
    print(f"  [WARN] LM Studio 不可達，{len(nodes)-covered} 個節點將無 embedding，"
          f"blocking 會遺漏這些節點")

# 5. LLM API（只測第一把 key）
print("\n[測試] Llama API（第一把 key）...")
try:
    client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=API_KEYS[0])
    r = client.chat.completions.create(
        model=LLAMA_MODEL,
        messages=[{"role": "user", "content": '{"decision":"same","confidence":0.9,"reason":"test"}'}],
        temperature=0.0, max_tokens=64,
        response_format={"type": "json_object"},
    )
    print(f"[OK] LLM API 可達：{r.choices[0].message.content[:80]}")
except Exception as e:
    print(f"[ERROR] LLM API 失敗：{e}")
    sys.exit(1)

print("\n✅ 前置確認完成，可執行 run_matchgpt.py")




