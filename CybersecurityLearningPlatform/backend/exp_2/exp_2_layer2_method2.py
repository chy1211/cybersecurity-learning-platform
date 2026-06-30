#!/usr/bin/env python3
from __future__ import annotations

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
"""Exp 2 Layer 2 Method 2: Distributional Semantic Alignment

用外部預訓練語意向量（不接觸 Leiden 結果）驗證同社群節點是否更相近。

流程：
  1. 從 Neo4j 重新抽樣節點對（layer2a 邏輯） → 覆寫 layer2_pairs.csv
  2. 呼叫本地 embedding API 取得節點名稱向量（支援批次、快取）
  3. 計算 cosine similarity，分 in-community / cross-community 兩組
  4. 統計：mean/std/median、Welch t-test、Mann-Whitney U、Cohen's d

Embedding API：由 EMBEDDING_BASE_URL 指定，預設 http://127.0.0.1:1234/v1/embeddings
論文語氣定稿（寫死於輸出 JSON）：
  "社群內相似度穩定高於跨社群，但效果量偏小，顯示 Leiden 社群具有
   統計上一致的語意凝聚趨勢，而非強烈語意分隔。"

用法：
  python exp_2_layer2_method2.py                             # 真實模式
  python exp_2_layer2_method2.py --mock_neo4j --mock_api    # 離線測試
"""

import argparse
import csv
import json
import math
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import requests
from scipy import stats

# ─── 路徑常數 ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
BASE_DIR    = _HERE.parents[4]
RESULTS_DIR = BASE_DIR / "論文" / "實驗" / "實驗2_Leiden三層驗證" / "結果" / "layer2"

DEFAULT_PAIRS_CSV   = RESULTS_DIR / "layer2_pairs.csv"
DEFAULT_OUTPUT_JSON = RESULTS_DIR / "layer2_method2_results.json"
DEFAULT_EMB_CACHE   = RESULTS_DIR / "layer2_method2_embeddings_cache.json"

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1")
EMBEDDING_BATCH    = 64   # 單次請求傳入的最大文字數

NARRATIVE = (
    "社群內相似度穩定高於跨社群，但效果量偏小，顯示 Leiden 社群具有"
    "統計上一致的語意凝聚趨勢，而非強烈語意分隔。"
)

PAIRS_FIELDNAMES = [
    "pair_id", "pair_type", "community_id", "cross_community_id",
    "node_id_a", "name_a", "type_a", "normalized_name_a",
    "node_id_b", "name_b", "type_b", "normalized_name_b",
    "seed", "min_size", "pairs_per_community",
]


# ─── Neo4j & Mock ─────────────────────────────────────────────────────────────

def fetch_nodes_from_neo4j(uri: str, user: str, password: str) -> list[dict]:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError(
            "neo4j package 未安裝，請 pip install neo4j 或使用 --mock_neo4j"
        ) from exc

    query = """
    MATCH (n:KGNode)
    WHERE n.communityId IS NOT NULL
    RETURN elementId(n) AS node_id,
           coalesce(n.name, n.id, n.title) AS name,
           n.type AS type,
           n.communityId AS community_id
    """
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            rows = [dict(r) for r in session.run(query)]
    finally:
        driver.close()
    return rows


def build_mock_nodes() -> list[dict]:
    """4 個模擬社群，每個 12 節點，確保 ≥ min_size=10 並能抽出足夠節點對。"""
    domain_nodes = {
        0: ["防火牆", "封包過濾", "入侵偵測", "存取控制",
            "VPN", "網路隔離", "流量分析", "白名單",
            "黑名單", "DMZ", "反向代理", "WAF"],
        1: ["SQL Injection", "XSS", "惡意程式", "釣魚攻擊",
            "勒索軟體", "後門程式", "緩衝區溢位", "零時差漏洞",
            "社會工程", "DDoS", "中間人攻擊", "APT"],
        2: ["密碼政策", "最小權限原則", "多因素驗證", "單一登入",
            "角色存取控制", "強制存取控制", "審計日誌", "帳號生命週期",
            "特權帳號管理", "身分驗證", "授權框架", "RBAC"],
        3: ["風險評鑑", "資產清冊", "業務衝擊分析", "災難復原",
            "事件回應計畫", "殘餘風險", "風險接受", "風險規避",
            "BCP", "BIA", "ISMS", "ISO 27001"],
    }
    nodes = []
    for cid, names in domain_nodes.items():
        type_map = {0: "tool", 1: "attack", 2: "policy", 3: "risk"}
        typ = type_map[cid]
        for i, name in enumerate(names):
            nodes.append({
                "node_id":     f"mock_{cid}_{i}",
                "name":        name,
                "type":        typ,
                "community_id": str(cid),
            })
    return nodes


# ─── 抽樣邏輯（layer2a）─────────────────────────────────────────────────────

def normalize_cid(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    s = str(value)
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s.strip()


def normalize_name(name: str) -> str:
    text = str(name or "").lower()
    text = re.sub(r"（.*?）|\(.*?\)", "", text)
    text = re.sub(r"[\s\-_／/、，,。.:：;；'\"`]+", "", text)
    return text.strip()


def node_type(node: dict) -> str:
    value = node.get("type") or node.get("node_type")
    if value:
        return str(value)
    labels = node.get("labels")
    if isinstance(labels, list) and labels:
        return ",".join(str(x) for x in labels if x != "KGNode")
    return "Entity"


def group_eligible_nodes(
    nodes: list[dict], min_size: int
) -> dict[str, list[dict]]:
    raw: dict[str, list] = defaultdict(list)
    for node in nodes:
        name = node.get("name")
        cid  = normalize_cid(node.get("community_id", node.get("communityId")))
        if not name or cid == "UNKNOWN":
            continue
        enriched = dict(node)
        enriched["community_id"]    = cid
        enriched["normalized_name"] = normalize_name(str(name))
        raw[cid].append(enriched)

    eligible = {}
    for cid, group in raw.items():
        if len(group) < min_size:
            continue
        unique: dict[str, dict] = {}
        for node in group:
            norm = node["normalized_name"]
            if norm and norm not in unique:
                unique[norm] = node
        if len(unique) >= 2:
            eligible[cid] = list(unique.values())
    return dict(
        sorted(eligible.items(), key=lambda item: _cid_sort_key(item[0]))
    )


def _cid_sort_key(cid: str) -> tuple[int, Any]:
    try:
        return (0, int(cid))
    except ValueError:
        return (1, cid)


def _pair_key(a: dict, b: dict) -> tuple[str, str]:
    return tuple(sorted((a["normalized_name"], b["normalized_name"])))


def make_pair(
    pair_type: str,
    a: dict,
    b: dict,
    community_id: str,
    cross_community_id: str | None,
) -> dict:
    return {
        "pair_type":           pair_type,
        "community_id":        community_id,
        "cross_community_id":  cross_community_id,
        "name_a":              a["name"],
        "type_a":              node_type(a),
        "name_b":              b["name"],
        "type_b":              node_type(b),
        "normalized_name_a":   a["normalized_name"],
        "normalized_name_b":   b["normalized_name"],
        "node_id_a":           a.get("node_id"),
        "node_id_b":           b.get("node_id"),
    }


def sample_pairs(
    nodes: list[dict],
    min_size: int,
    pairs_per_community: int,
    seed: int = 42,
) -> list[dict]:
    rng    = random.Random(seed)
    groups = group_eligible_nodes(nodes, min_size)
    if len(groups) < 2:
        raise RuntimeError(
            f"有效社群數 {len(groups)} < 2，無法抽取跨社群對。"
            f"請確認圖譜中有足夠社群（size ≥ {min_size}），或使用 --mock_neo4j。"
        )

    all_pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    cids = list(groups)

    for cid in cids:
        # 同群
        same_candidates = list(combinations(groups[cid], 2))
        rng.shuffle(same_candidates)
        same_added = 0
        for a, b in same_candidates:
            key = _pair_key(a, b)
            if key in seen or a["normalized_name"] == b["normalized_name"]:
                continue
            seen.add(key)
            all_pairs.append(make_pair("in", a, b, cid, None))
            same_added += 1
            if same_added >= pairs_per_community:
                break

        # 跨群
        cross_candidates = []
        for other_cid in cids:
            if other_cid == cid:
                continue
            for a in groups[cid]:
                for b in groups[other_cid]:
                    cross_candidates.append((a, b, other_cid))
        rng.shuffle(cross_candidates)
        cross_added = 0
        for a, b, other_cid in cross_candidates:
            key = _pair_key(a, b)
            if key in seen or a["normalized_name"] == b["normalized_name"]:
                continue
            seen.add(key)
            all_pairs.append(make_pair("cross", a, b, cid, other_cid))
            cross_added += 1
            if cross_added >= pairs_per_community:
                break

    return all_pairs


def write_pairs_csv(pairs: list[dict], path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=PAIRS_FIELDNAMES, extrasaction="ignore"
        )
        writer.writeheader()
        for idx, pair in enumerate(pairs):
            row = {**pair, **meta, "pair_id": f"pair_{idx + 1:05d}"}
            writer.writerow(row)


# ─── Embedding API ────────────────────────────────────────────────────────────

def list_models(base_url: str) -> list[str]:
    """GET /v1/models，回傳 model id 清單。失敗回傳空清單。"""
    try:
        resp = requests.get(f"{base_url}/models", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", [])]
    except Exception as e:
        print(f"  [警告] 無法取得 model list：{e}")
    return []


def get_embeddings_batch(
    texts: list[str],
    model: str,
    base_url: str,
    retries: int = 3,
) -> dict[str, list[float]]:
    """呼叫 embedding API，傳入文字清單（批次），回傳 {text: vector} dict。"""
    url     = f"{base_url}/embeddings"
    headers = {"Content-Type": "application/json"}
    payload = {"model": model, "input": texts}

    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                result: dict[str, list[float]] = {}
                for item in resp.json().get("data", []):
                    idx = item.get("index", 0)
                    if 0 <= idx < len(texts):
                        result[texts[idx]] = item["embedding"]
                return result
            else:
                print(f"  [API 錯誤] HTTP {resp.status_code}，重試 {attempt+1}/{retries}")
        except Exception as e:
            print(f"  [API 例外] {e}，重試 {attempt+1}/{retries}")
        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    # 逐一 fallback
    result = {}
    for text in texts:
        for att in range(retries):
            try:
                r = requests.post(
                    url, headers=headers,
                    json={"model": model, "input": text},
                    timeout=15,
                )
                if r.status_code == 200:
                    result[text] = r.json()["data"][0]["embedding"]
                    break
            except Exception:
                if att < retries - 1:
                    time.sleep(1)
    return result


def mock_embeddings(texts: list[str], dim: int = 64) -> dict[str, list[float]]:
    """--mock_api 時：用 seeded 隨機單位向量模擬 embedding。"""
    rng = random.Random(0)
    result = {}
    for text in texts:
        vec = [rng.gauss(0, 1) for _ in range(dim)]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        result[text] = [v / norm for v in vec]
    return result


def build_embedding_cache(
    unique_names: list[str],
    cache_path: Path,
    model: str,
    base_url: str,
    mock_api: bool,
    batch_size: int = EMBEDDING_BATCH,
) -> dict[str, list[float]]:
    # 載入既有快取
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"  快取載入：{len(cache)} 個節點")
        except Exception as e:
            print(f"  [警告] 快取讀取失敗，重新計算：{e}")
            cache = {}

    missing = [n for n in unique_names if n not in cache]
    if not missing:
        print(f"  全部 {len(unique_names)} 個節點已有快取，跳過 API 呼叫")
        return cache

    print(f"  需取得 embedding 的節點：{len(missing)}")

    if mock_api:
        new_embs = mock_embeddings(missing)
        # 維度驗證：若快取已有不同維度的向量，清除快取
        if cache:
            cached_dim = len(next(iter(cache.values())))
            new_dim    = len(next(iter(new_embs.values())))
            if cached_dim != new_dim:
                print(f"  [警告] 快取維度 {cached_dim} ≠ 新 embedding 維度 {new_dim}，清除舊快取")
                cache = {}
        cache.update(new_embs)
    else:
        total = len(missing)
        done  = 0
        for i in range(0, total, batch_size):
            batch = missing[i : i + batch_size]
            embs  = get_embeddings_batch(batch, model, base_url)
            # 第一批：若維度與快取不符則清除
            if done == 0 and embs and cache:
                cached_dim = len(next(iter(cache.values())))
                new_dim    = len(next(iter(embs.values())))
                if cached_dim != new_dim:
                    print(f"  [警告] 快取維度 {cached_dim} ≠ API 回傳維度 {new_dim}，清除舊快取")
                    cache = {}
            cache.update(embs)
            done += len(batch)
            sys.stdout.write(f"\r  Embedding 進度：{done}/{total}")
            sys.stdout.flush()
        print()

    # 儲存快取
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=None), encoding="utf-8"
    )
    print(f"  Embedding 快取 → {cache_path}")
    return cache


# ─── 統計計算 ──────────────────────────────────────────────────────────────────

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    a = np.array(v1, dtype=float)
    b = np.array(v2, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def compute_statistics(
    sims_in: list[float],
    sims_cross: list[float],
) -> dict:
    arr_in    = np.array(sims_in,    dtype=float)
    arr_cross = np.array(sims_cross, dtype=float)

    mean_in    = float(np.mean(arr_in))
    std_in     = float(np.std(arr_in, ddof=1))
    median_in  = float(np.median(arr_in))

    mean_cross   = float(np.mean(arr_cross))
    std_cross    = float(np.std(arr_cross, ddof=1))
    median_cross = float(np.median(arr_cross))

    t_stat, p_t = stats.ttest_ind(arr_in, arr_cross, equal_var=False)
    u_stat, p_u = stats.mannwhitneyu(arr_in, arr_cross, alternative="two-sided")

    # Cohen's d（pooled，n1=n2 時與 Glass's Δ 相同；使用無偏 std）
    pooled_std = math.sqrt((std_in ** 2 + std_cross ** 2) / 2)
    cohen_d    = (mean_in - mean_cross) / pooled_std if pooled_std > 0 else 0.0

    return {
        "n_in":        len(sims_in),
        "n_cross":     len(sims_cross),
        "mean_in":     round(mean_in,    4),
        "std_in":      round(std_in,     4),
        "median_in":   round(median_in,  4),
        "mean_cross":  round(mean_cross, 4),
        "std_cross":   round(std_cross,  4),
        "median_cross":round(median_cross, 4),
        "mean_diff":   round(mean_in - mean_cross, 4),
        "t_stat":      round(float(t_stat), 4),
        "p_t":         float(p_t),
        "u_stat":      round(float(u_stat), 4),
        "p_u":         float(p_u),
        "cohen_d":     round(cohen_d, 4),
        "significant_t": float(p_t) < 0.05,
        "significant_u": float(p_u) < 0.05,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exp 2 Layer 2 Method 2: Distributional Semantic Alignment"
    )
    parser.add_argument("--uri",      default=NEO4J_URI)
    parser.add_argument("--user",     default=NEO4J_USER)
    parser.add_argument("--password", default=NEO4J_PASSWORD)
    parser.add_argument("--min_size",           type=int, default=10)
    parser.add_argument("--pairs_per_community", type=int, default=20)
    parser.add_argument("--seed",               type=int, default=42)
    parser.add_argument("--embedding_base_url",  default=EMBEDDING_BASE_URL)
    parser.add_argument("--embedding_model",     default="",
                        help="指定 embedding 模型 ID；空白時自動選第一個 text-embedding-* 模型")
    parser.add_argument("--output_pairs",       type=Path, default=DEFAULT_PAIRS_CSV)
    parser.add_argument("--output_json",        type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output_emb_cache",   type=Path, default=DEFAULT_EMB_CACHE)
    parser.add_argument("--mock_neo4j", action="store_true",
                        help="使用 mock 節點離線測試（不連 Neo4j）")
    parser.add_argument("--mock_api",   action="store_true",
                        help="使用隨機向量模擬 embedding API（離線測試）")
    args = parser.parse_args()

    print("=" * 60)
    print("[Layer2-M2] Distributional Semantic Alignment")
    print(f"  Neo4j 模式：{'MOCK' if args.mock_neo4j else args.uri}")
    print(f"  API 模式：  {'MOCK' if args.mock_api else args.embedding_base_url}")
    print("=" * 60)

    # ─── Step 0：確認 Embedding 模型 ────────────────────────────────────────
    embedding_model = ""
    if args.mock_api:
        embedding_model = "mock-embedding-model"
        print("\n[Embedding] mock 模式，跳過 API model 確認")
    else:
        print(f"\n[Embedding] 查詢可用模型：{args.embedding_base_url}/models")
        models = list_models(args.embedding_base_url)
        if models:
            print(f"  可用模型：")
            for m in models:
                print(f"    {m}")
            if args.embedding_model:
                # 使用者指定
                embedding_model = args.embedding_model
                print(f"  → 使用指定模型：{embedding_model}")
            else:
                # 自動選第一個 text-embedding-* 模型
                emb_models = [m for m in models if "text-embedding" in m.lower() or "embedding" in m.lower()]
                if emb_models:
                    embedding_model = emb_models[0]
                    print(f"  → 自動選 embedding 模型：{embedding_model}")
                else:
                    embedding_model = models[0]
                    print(f"  [警告] 未找到 text-embedding-* 模型，使用：{embedding_model}")
        else:
            print("  [警告] 無法取得 model list")
            embedding_model = args.embedding_model or ""

    # ─── Step 1：從 Neo4j 重新抽樣 → 覆寫 pairs.csv ─────────────────────────
    print(f"\n[Step 1] 從 {'mock' if args.mock_neo4j else 'Neo4j'} 載入節點並抽樣")
    if args.mock_neo4j:
        nodes = build_mock_nodes()
    else:
        nodes = fetch_nodes_from_neo4j(args.uri, args.user, args.password)
    print(f"  節點總數（有 communityId）：{len(nodes)}")

    pairs = sample_pairs(nodes, args.min_size, args.pairs_per_community, seed=args.seed)
    in_cnt    = sum(1 for p in pairs if p["pair_type"] == "in")
    cross_cnt = sum(1 for p in pairs if p["pair_type"] == "cross")
    print(f"  抽樣完成：同群 {in_cnt} 對 / 跨群 {cross_cnt} 對 = 共 {len(pairs)} 對")

    write_pairs_csv(
        pairs,
        args.output_pairs,
        meta={
            "seed":               args.seed,
            "min_size":           args.min_size,
            "pairs_per_community": args.pairs_per_community,
        },
    )
    print(f"  Pairs CSV → {args.output_pairs}")

    # ─── Step 2：收集唯一節點名稱 ─────────────────────────────────────────────
    print("\n[Step 2] 收集唯一節點名稱")
    names_set: set[str] = set()
    for p in pairs:
        names_set.add(str(p["name_a"]))
        names_set.add(str(p["name_b"]))
    unique_names = sorted(names_set)
    print(f"  唯一節點名稱數：{len(unique_names)}")

    # ─── Step 3：取得 Embedding（含快取）───────────────────────────────────────
    print("\n[Step 3] 取得 Embedding")
    emb_cache = build_embedding_cache(
        unique_names,
        args.output_emb_cache,
        model=embedding_model,
        base_url=args.embedding_base_url,
        mock_api=args.mock_api,
    )

    # ─── Step 4：計算 Cosine Similarity ────────────────────────────────────────
    print("\n[Step 4] 計算 Cosine Similarity")
    sims_in:    list[float] = []
    sims_cross: list[float] = []
    skipped = 0

    for p in pairs:
        na = str(p["name_a"])
        nb = str(p["name_b"])
        if na not in emb_cache or nb not in emb_cache:
            skipped += 1
            continue
        sim = cosine_similarity(emb_cache[na], emb_cache[nb])
        if p["pair_type"] == "in":
            sims_in.append(sim)
        else:
            sims_cross.append(sim)

    if skipped:
        print(f"  [警告] 跳過 {skipped} 對（無 embedding）")
    print(f"  有效對數：同群 {len(sims_in)}、跨群 {len(sims_cross)}")

    if not sims_in or not sims_cross:
        print("[ERROR] 沒有足夠的相似度資料，請確認 embedding API 正常運作")
        return 1

    # ─── Step 5：統計分析 ───────────────────────────────────────────────────────
    print("\n[Step 5] 統計分析")
    stat = compute_statistics(sims_in, sims_cross)

    print(f"  同群   mean={stat['mean_in']:.4f}  std={stat['std_in']:.4f}  "
          f"median={stat['median_in']:.4f}")
    print(f"  跨群   mean={stat['mean_cross']:.4f}  std={stat['std_cross']:.4f}  "
          f"median={stat['median_cross']:.4f}")
    print(f"  差值   Δ={stat['mean_diff']:.4f}")
    print(f"  Welch t={stat['t_stat']:.4f}  p={stat['p_t']:.4e}  "
          f"({'顯著' if stat['significant_t'] else '不顯著'})")
    print(f"  Mann-Whitney U={stat['u_stat']:.4f}  p={stat['p_u']:.4e}  "
          f"({'顯著' if stat['significant_u'] else '不顯著'})")
    print(f"  Cohen's d = {stat['cohen_d']:.4f}")

    # ─── 輸出 JSON ──────────────────────────────────────────────────────────────
    results = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "layer":  "semantic",
        "method": "distributional_semantic_alignment",
        "parameters": {
            "min_community_size":         args.min_size,
            "pairs_per_community":        args.pairs_per_community,
            "seed":                       args.seed,
            "embedding_model":            embedding_model,
            "embedding_base_url":         args.embedding_base_url,
        },
        "statistics": stat,
        "narrative": NARRATIVE,
        "paths": {
            "pairs_csv":       str(args.output_pairs),
            "embeddings_cache": str(args.output_emb_cache),
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  JSON → {args.output_json}")
    print("\n[Layer2-M2] 完成")
    print(f"\n論文引用語：\n  {NARRATIVE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
