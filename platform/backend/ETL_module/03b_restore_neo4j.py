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
from tqdm import tqdm
from neo4j import GraphDatabase

# --- Neo4j 設定 ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- 參數設定 ---
VALIDATED_DIR = "Validated"

def import_to_neo4j(session, t):
    s_name = t['subject']['name']
    o_name = t['object']['name']
    # display_name：保留原始大小寫供 UI 顯示，fallback 為 name
    display_s_name = t['subject'].get('display_name', s_name).strip()
    display_o_name = t['object'].get('display_name', o_name).strip()
    s_type = t['subject']['type']
    relation = t['relation']
    o_type = t['object']['type']

    # 確保 label 與 relation 安全性 (移除非英數字元)
    s_type_safe = "".join([c for c in s_type if c.isalnum()])
    o_type_safe = "".join([c for c in o_type if c.isalnum()])
    relation_safe = "".join([c for c in relation if c.isalnum() or c == '_'])

    query = f"""
    MERGE (s:{s_type_safe} {{name: $s_name}})
    ON CREATE SET s.display_name = $display_s_name
    SET s.source_file = coalesce(s.source_file, []) + [$source_file],
        s.source_id = coalesce(s.source_id, []) + [$source_id],
        s.source_index = coalesce(s.source_index, []) + [$source_index]
    MERGE (o:{o_type_safe} {{name: $o_name}})
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
        s_name=s_name, 
        o_name=o_name, 
        display_s_name=display_s_name,
        display_o_name=display_o_name,
        source_file=t.get('source_file', ''),
        source_id=t.get('source_id', ''),
        source_index=t.get('source_index', '')
    )

def get_validated_files(val_dir):
    files = []
    for root, _, filenames in os.walk(val_dir):
        for f in filenames:
            if f.endswith('.json'):
                files.append(os.path.join(root, f))
    return files

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if not os.path.exists(VALIDATED_DIR):
        print(f"找不到 Validated 資料夾: {os.path.abspath(VALIDATED_DIR)}")
        return

    val_files = get_validated_files(VALIDATED_DIR)
    
    if not val_files:
        print(f"Validated 資料夾內沒有找到任何 JSON 檔案。")
        return

    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        neo4j_driver.verify_connectivity()
        print("Neo4j 連線成功。")
    except Exception as e:
        print(f"Neo4j 連線失敗: {e}")
        exit(1)

    print("\n=======================================================")
    print("⚠️  強烈建議：如果您是要進行完整的資料庫「還原」作業")
    print("   請先手動清空 Neo4j 內現有的資料，以免殘留舊節點。")
    print("   (清空指令: MATCH (n) DETACH DELETE n)")
    print("=======================================================\n")
    
    # Python 3 內建的簡單輸入停頓
    input("按 Enter 鍵繼續開始還原匯入，或按 Ctrl+C 取消...")

    print(f"\n開始從 Validated 還原資料 (總共 {len(val_files)} 個檔案)...")
    
    total_restored = 0

    # 為了確保寫入安全與效率，此處使用單一 session 依序還原
    with neo4j_driver.session() as session:
        for file_path in tqdm(val_files, desc="檔案處理進度", unit="file"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    triples = json.load(f)
            except json.JSONDecodeError as e:
                print(f"\n[警告] 檔案解析失敗 (JSON 格式錯誤)，略過: {file_path}")
                continue
                
            if not isinstance(triples, list) or len(triples) == 0:
                continue
            
            # 將每個檔案內的 triples 寫入 Neo4j
            for t in triples:
                try:
                    import_to_neo4j(session, t)
                    total_restored += 1
                except Exception as exc:
                    print(f"\n[錯誤] 寫入三元組失敗: {t} -> {exc}")

    neo4j_driver.close()
    print("\n======================================")
    print(f"資料庫還原完成！")
    print(f"成功匯入三元組: {total_restored} 筆")
    print("======================================")

if __name__ == "__main__":
    main()



