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
"""
restore_platform_kg.py
======================
一鍵還原平台格式 final 圖譜。

用法：
  python phase1_scripts\restore_platform_kg.py          # 從備份快速還原（推薦）
  python phase1_scripts\restore_platform_kg.py --rebuild # 從 Validated/ 重跑完整流程

說明：
  --rebuild  清空 Neo4j → 03b 格式重新匯入 → 套用 MatchGPT 合併（約 7 分鐘）
  預設       用 final_platform_kg.json 備份直接還原（約 2 分鐘，有 0.8% 關係損失）
"""

import sys
from pathlib import Path

MATCHGPT_DIR = Path(__file__).parent.parent

def restore_from_backup():
    sys.path.insert(0, str(MATCHGPT_DIR))
    import neo4j_backup_restore as nbr
    from neo4j import GraphDatabase

    backup = MATCHGPT_DIR / "phase1_backups" / "final_platform_kg.json"
    if not backup.exists():
        print(f"[ERROR] 找不到備份 {backup}")
        print("       請先執行 apply_matchgpt_to_platform.py 生成備份，")
        print("       或用 --rebuild 旗標從頭重建。")
        sys.exit(1)

    driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
                                  auth=("neo4j", os.getenv("NEO4J_PASSWORD", "")))
    print(f"從備份還原：{backup.name}")
    nbr.restore(driver, str(backup), wipe=True)
    driver.close()
    print("✅ 還原完成（平台格式 final 圖譜）")
    print("   已知限制：備份工具對同對節點多條邊有 ~0.8% 損失，若需完全精確請用 --rebuild")

def rebuild_from_scratch():
    import subprocess
    script = MATCHGPT_DIR / "phase1_scripts" / "apply_matchgpt_to_platform.py"
    print("從頭重建平台格式 final 圖譜（Validated/ → 平台格式匯入 → MatchGPT 合併）...")
    result = subprocess.run([sys.executable, "-u", str(script)],
                            cwd=str(MATCHGPT_DIR))
    sys.exit(result.returncode)

if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        rebuild_from_scratch()
    else:
        restore_from_backup()


