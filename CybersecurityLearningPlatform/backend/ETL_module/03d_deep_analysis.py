"""
03d_deep_analysis.py
全面掃描 Validated/ 目錄的所有 .json，統計以下問題：
1. URI 標準化（Step2 duplicate）成功多少次 / 失敗多少次
2. 未被合併的「潛在同義詞」在 Validated JSON 裡還存在多少
3. 連線 Neo4j，列出圖上實際存在的高度相似節點（冗餘節點）
4. 分析 Step2 prompt 邏輯盲點
"""

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
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher

# ── Neo4j 連線設定 ────────────────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

VALIDATED_DIR = Path(__file__).resolve().parent / "Validated"

# ── 工具函數 ───────────────────────────────────────────────────────────────────
def load_all_validated_json():
    """回傳 (file_path, record) 的 generator"""
    for json_file in sorted(VALIDATED_DIR.rglob("*.json")):
        if not json_file.is_file():
            continue
        try:
            with json_file.open("r", encoding="utf-8") as f:
                records = json.load(f)
            if isinstance(records, list):
                for rec in records:
                    yield json_file, rec
        except Exception as e:
            print(f"[WARN] 無法讀取 {json_file}: {e}")

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# ── 分析1: URI 標準化命中率 ────────────────────────────────────────────────────
def analyze_uri_standardization():
    print("\n" + "="*60)
    print("【分析 1】URI 標準化 (Step 2 duplicate) 統計")
    print("="*60)

    total = 0
    has_original = 0
    step2_exists = 0
    step2_duplicate = 0
    step2_correct = 0
    step2_no_ldr = 0    # Ldr 為空時 Step2 直接 correct
    subject_renamed = 0
    object_renamed = 0
    changed_examples = []

    for _, rec in load_all_validated_json():
        total += 1
        original = rec.get("original_raw_triple")
        if not isinstance(original, dict):
            continue
        has_original += 1

        step2 = rec.get("validation_history", {}).get("step_2")
        if step2 is None:
            step2_no_ldr += 1   # 沒有進行 Step2（Ldr 為空跳過，或例外）
            continue

        step2_exists += 1
        response = step2.get("response", "")
        if response == "duplicate":
            step2_duplicate += 1
        else:
            step2_correct += 1

        # 實際有無改名
        orig_sub = original.get("subject", {}).get("name", "")
        orig_obj = original.get("object", {}).get("name", "")
        final_sub = rec.get("subject", {}).get("name", "")
        final_obj = rec.get("object", {}).get("name", "")

        sub_changed = orig_sub != final_sub
        obj_changed = orig_obj != final_obj

        if sub_changed:
            subject_renamed += 1
        if obj_changed:
            object_renamed += 1

        if (sub_changed or obj_changed) and len(changed_examples) < 20:
            changed_examples.append({
                "orig_sub": orig_sub,  "final_sub": final_sub,
                "orig_obj": orig_obj,  "final_obj": final_obj,
                "step2_response": response,
                "granularity_analysis": step2.get("granularity_analysis", ""),
            })

    print(f"總驗證通過筆數: {total}")
    print(f"有 original_raw_triple: {has_original}")
    print(f"進行了 Step2 (有 validation_history.step_2): {step2_exists}")
    print(f"  → Step2 判定 duplicate (嘗試合併): {step2_duplicate}")
    print(f"  → Step2 判定 correct   (不合併):   {step2_correct}")
    print(f"未進入 Step2 (Ldr 為空/例外): {step2_no_ldr}")
    print(f"實際改名 subject: {subject_renamed}")
    print(f"實際改名 object:  {object_renamed}")

    if changed_examples:
        print(f"\n改名範例（最多 20 筆）：")
        for i, ex in enumerate(changed_examples, 1):
            print(f"  [{i}] subject: '{ex['orig_sub']}' → '{ex['final_sub']}'")
            print(f"       object:  '{ex['orig_obj']}' → '{ex['final_obj']}'")
            print(f"       Step2回應: {ex['step2_response']}")
            if ex['granularity_analysis']:
                print(f"       分析: {ex['granularity_analysis'][:120]}...")
    
    return step2_duplicate, step2_correct, step2_no_ldr

# ── 分析2: Validated JSON 裡存在多少潛在同義詞對 ──────────────────────────────
def analyze_redundant_in_validated():
    print("\n" + "="*60)
    print("【分析 2】Validated JSON 內部：同類節點間潛在同義詞統計")
    print("="*60)

    # 收集所有最終節點名稱（按 type 分組）
    by_type = defaultdict(set)
    for _, rec in load_all_validated_json():
        s = rec.get("subject", {})
        o = rec.get("object", {})
        if s.get("name") and s.get("type"):
            by_type[s["type"]].add(s["name"])
        if o.get("name") and o.get("type"):
            by_type[o["type"]].add(o["name"])

    print(f"\n各類別節點數量：")
    for t, names in sorted(by_type.items()):
        print(f"  {t}: {len(names)} 個")

    # 找高相似度對（>= 0.75）
    suspicious_pairs = []
    for t, names in by_type.items():
        name_list = sorted(names)
        for i in range(len(name_list)):
            for j in range(i+1, len(name_list)):
                a, b = name_list[i], name_list[j]
                sim = similarity(a, b)
                if sim >= 0.75:
                    suspicious_pairs.append((t, a, b, sim))

    suspicious_pairs.sort(key=lambda x: -x[3])

    print(f"\n高相似度節點對（相似度 >= 0.75，共 {len(suspicious_pairs)} 對）：")
    for t, a, b, sim in suspicious_pairs[:60]:
        print(f"  [{t}] '{a}' ↔ '{b}'  (sim={sim:.3f})")
    
    if len(suspicious_pairs) > 60:
        print(f"  ... 還有 {len(suspicious_pairs)-60} 對")

    return suspicious_pairs, by_type

# ── 分析3: 連線 Neo4j 找圖上冗餘節點 ──────────────────────────────────────────
def analyze_neo4j_redundancy():
    print("\n" + "="*60)
    print("【分析 3】Neo4j 圖資料庫中實際存在的相似節點")
    print("="*60)

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("[ERROR] 需要安裝 neo4j 套件")
        return

    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("Neo4j 連線成功")
    except Exception as e:
        print(f"[ERROR] Neo4j 連線失敗: {e}")
        return

    node_classes = [
        "feature", "function", "attack", "vulnerability", "technique", "data",
        "principle", "risk", "tool", "system", "app", "policy", "attacker",
        "securityTeam", "user"
    ]

    all_redundant_pairs = []

    with driver.session() as session:
        print(f"\n各標籤節點總數：")
        for label in node_classes:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            cnt = result.single()["cnt"]
            print(f"  {label}: {cnt} 個")

        print(f"\n逐類別掃描相似節點（閾值 0.72）...")
        for label in node_classes:
            result = session.run(f"MATCH (n:{label}) RETURN DISTINCT n.name AS name ORDER BY name")
            names = [r["name"] for r in result if r["name"]]
            
            for i in range(len(names)):
                for j in range(i+1, len(names)):
                    a, b = names[i], names[j]
                    sim = similarity(a, b)
                    if sim >= 0.72:
                        all_redundant_pairs.append((label, a, b, sim))

    all_redundant_pairs.sort(key=lambda x: -x[3])
    
    print(f"\nNeo4j 圖上高相似度節點對（共 {len(all_redundant_pairs)} 對）：")
    for label, a, b, sim in all_redundant_pairs[:80]:
        print(f"  [{label}] '{a}' ↔ '{b}'  (sim={sim:.3f})")
    
    if len(all_redundant_pairs) > 80:
        print(f"  ... 還有 {len(all_redundant_pairs)-80} 對")

    driver.close()
    return all_redundant_pairs

# ── 分析4: Step2 為何沒有合併 ─────────────────────────────────────────────────
def analyze_step2_missed_merges():
    print("\n" + "="*60)
    print("【分析 4】Step2 判定 correct 但原始與Ldr間可能應合併的案例")
    print("="*60)

    missed = []
    for _, rec in load_all_validated_json():
        step2 = rec.get("validation_history", {}).get("step_2")
        if not step2 or step2.get("response") != "correct":
            continue
        
        orig = rec.get("original_raw_triple", {})
        orig_sub = orig.get("subject", {}).get("name", "")
        orig_obj = orig.get("object", {}).get("name", "")
        final_sub = rec.get("subject", {}).get("name", "")
        final_obj = rec.get("object", {}).get("name", "")
        
        # 注意：若 Step2 correct 但原始就跟 final 不同（不應發生），那就是 bug
        # 主要看 LLM 給的 granularity_analysis 是否與 correct 結論矛盾
        ga = step2.get("granularity_analysis", "")
        reason = step2.get("reason", "")
        
        # 找 granularity_analysis 有提到「同義」但仍判定 correct 的矛盾案例
        keywords_synonym = ["同義", "synonym", "同一", "相同意思", "相同概念", "類似"]
        keywords_hier = ["廣義", "狹義", "從屬", "包含", "taxonomy", "種類", "不同層級", "不同概念", "不同階層"]
        
        has_synonym_hint = any(kw in ga.lower() or kw in reason.lower() for kw in keywords_synonym)
        has_hier_hint    = any(kw in ga.lower() or kw in reason.lower() for kw in keywords_hier)
        
        if has_synonym_hint and not has_hier_hint and len(missed) < 30:
            missed.append({
                "sub": final_sub, "obj": final_obj,
                "step2_reason": reason[:150],
                "granularity": ga[:200],
            })

    print(f"\nStep2 判定 correct 但分析有同義詞暗示的案例（共 {len(missed)} 筆）：")
    for i, m in enumerate(missed[:30], 1):
        print(f"  [{i}] sub='{m['sub']}' obj='{m['obj']}'")
        print(f"       reason: {m['step2_reason']}")
        print(f"       granularity: {m['granularity'][:120]}")

    return missed

# ── 分析5: Ldr 為空導致跳過 Step2 的情況 ─────────────────────────────────────
def analyze_empty_ldr_cases():
    print("\n" + "="*60)
    print("【分析 5】Ldr 為空 → Step2 未觸發 → 潛在同義詞直接寫入")
    print("="*60)

    # 找沒有 step_2 的記錄，但其 subject/object 有高相似度
    no_step2_names = []
    for _, rec in load_all_validated_json():
        step2 = rec.get("validation_history", {}).get("step_2")
        if step2 is not None:
            continue
        s_name = rec.get("subject", {}).get("name", "")
        o_name = rec.get("object", {}).get("name", "")
        s_type = rec.get("subject", {}).get("type", "")
        o_type = rec.get("object", {}).get("type", "")
        if s_name:
            no_step2_names.append((s_name, s_type))
        if o_name:
            no_step2_names.append((o_name, o_type))

    print(f"沒有 Step2 記錄的節點共 {len(no_step2_names)} 個（含重複）")

    # 統計前30高頻無Step2節點
    from collections import Counter
    counter = Counter([(n, t) for n, t in no_step2_names])
    print(f"\n出現最多次但從未進行 Step2 的節點（Top 30）：")
    for (name, typ), cnt in counter.most_common(30):
        print(f"  [{typ}] '{name}' 出現 {cnt} 次")

# ── 主程式 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  知識圖譜驗證管線深度分析報告")
    print("=" * 60)

    analyze_uri_standardization()
    suspicious_pairs, by_type = analyze_redundant_in_validated()
    analyze_neo4j_redundancy()
    analyze_step2_missed_merges()
    analyze_empty_ldr_cases()

    print("\n\n" + "="*60)
    print("  分析完成")
    print("="*60)
