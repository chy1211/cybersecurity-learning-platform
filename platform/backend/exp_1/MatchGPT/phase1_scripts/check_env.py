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
from neo4j import GraphDatabase

driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"), auth=("neo4j", os.getenv("NEO4J_PASSWORD", "")))
with driver.session() as s:
    r = s.run("RETURN 1 AS ping")
    print("Neo4j 連線 OK:", r.single()["ping"])

    try:
        s.run("CALL apoc.help('apoc')").consume()
        print("APOC: OK")
    except Exception as e:
        print("APOC: 錯誤 -", e)

    try:
        r2 = s.run("CALL gds.list() YIELD name RETURN count(name) AS n")
        print("GDS: OK, 共", r2.single()["n"], "個演算法")
    except Exception as e:
        print("GDS: 錯誤 -", e)

    n = s.run("MATCH (n) RETURN count(n) AS cnt").single()["cnt"]
    rel = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
    print(f"當前 DB：{n} 節點 / {rel} 關係")

driver.close()


