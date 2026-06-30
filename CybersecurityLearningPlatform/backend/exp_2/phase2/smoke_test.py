#!/usr/bin/env python3
import os
import sys
from phase2_common import open_driver, drop_gds_graph, platform_rel_projection

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


"""快速測試平台格式圖譜的 GDS 投影與 KGNode 查詢是否正常。"""

sys.path.insert(0, ".")

driver = open_driver(os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"), "neo4j", os.getenv("NEO4J_PASSWORD", ""))
with driver.session() as s:
    # 1. 確認 KGNode 存在
    n = s.run("MATCH (n:KGNode) RETURN count(n) AS c").single()["c"]
    print(f"KGNode 節點數：{n}")
    assert n > 0, "找不到 KGNode！請先執行 apply_matchgpt_to_platform.py"

    # 2. 確認 type 屬性
    typed = s.run("MATCH (n:KGNode) WHERE n.type IS NOT NULL RETURN count(n) AS c").single()["c"]
    print(f"有 type 屬性的 KGNode：{typed}")

    # 3. GDS 投影測試
    drop_gds_graph(s, "smoke_test_kg")
    rec = s.run(
        "CALL gds.graph.project($gn, $nl, $rp) "
        "YIELD graphName, nodeCount, relationshipCount "
        "RETURN graphName, nodeCount, relationshipCount",
        gn="smoke_test_kg",
        nl="KGNode",
        rp=platform_rel_projection("UNDIRECTED"),
    ).single()
    print(f"GDS 投影成功：{dict(rec)}")
    drop_gds_graph(s, "smoke_test_kg")

driver.close()
print("✅ smoke test 通過")
