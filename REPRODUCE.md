# 復現指引

從零開始把平台跑起來、或重跑三個評估實驗。
本文件的環境與步驟於 **2026-08-04 在 Windows 11 實機驗證**；每個區段末尾標註了驗證狀態。

圖譜權威狀態：**2,763 節點／3,803 關係／87 分群**（2026-07 全鏈重跑定版）。

---

## 0. 環境需求

| 元件 | 版本 | 備註 |
|---|---|---|
| Python | 3.11–3.13 | 相依依用途分檔，見 `CybersecurityLearningPlatform/backend/requirements-*.txt` |
| Node.js | 18+ | 前端以 Vite 5 建置 |
| Java | **17 或 21** | Neo4j 5.26 LTS 的支援範圍 |
| Neo4j | **5.26.28** Community | 見下方外掛版本對應 |
| APOC | **與 Neo4j 同版**（5.26.28） | 平台 Cypher 使用 `apoc.meta.cypher.type`，**必要** |
| GDS | **2.13.11** | 僅實驗二需要 |

> ### ⚠ GDS 版本必須逐個 patch 版對照，不能拿最新版
> GDS 依 Neo4j patch 版發行。實測把 GDS **2.27.0**（2.x 系列最新）裝在 Neo4j 5.26.28 上，
> 伺服器能正常啟動、`gds.version()` 也答得出來，但一呼叫 `gds.graph.project.cypher` 就拋
> `ClassNotFoundException: org.neo4j.internal.kernel.api.security.StaticAccessMode`。
> 正確版本查 <https://graphdatascience.ninja/versions.json>（欄位 `neo4j` → `version`）。
> `tools/check_neo4j_env.py` 會自動幫你比對。

---

## 1. 準備 Neo4j

```powershell
# 1) 取得 Neo4j 5.26.28 Community 並解壓到你選定的目錄（以下用 C:\neo4j 為例）
#    https://dist.neo4j.org/neo4j-community-5.26.28-windows.zip

# 2) 放入外掛
#    APOC: https://github.com/neo4j/apoc/releases/download/5.26.28/apoc-5.26.28-core.jar
#    GDS : https://graphdatascience.ninja/neo4j-graph-data-science-2.13.11.jar
#    兩個 .jar 都放進 C:\neo4j\plugins\

# 3) 在 C:\neo4j\conf\neo4j.conf 末尾追加
#    dbms.security.procedures.unrestricted=apoc.*,gds.*
#    dbms.security.procedures.allowlist=apoc.*,gds.*

# 4) 設定初始密碼（務必在第一次啟動前執行）
$env:NEO4J_HOME = 'C:\neo4j'
& C:\neo4j\bin\neo4j-admin.bat dbms set-initial-password <your-password>

# 5) 啟動（前景）
& C:\neo4j\bin\neo4j.bat console
```

若環境變數 `NEO4J_HOME` 指向舊安裝，`neo4j-admin` 會以 exit 64 失敗並印出它實際採用的路徑——
以該訊息為準修正即可。

**驗證狀態：✅ 實機完成**（2026-08-04 於 Windows 11、Java 21.0.11）

---

## 2. 載入圖譜

repo 內附權威圖譜快照（平台格式，含分群屬性）：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\exp_1\MatchGPT'
python neo4j_backup_restore.py restore ..\..\..\..\data\kg_snapshot\platform_kg.json --wipe
```

- **務必加 `--wipe`**：只有 wipe 模式會逐條 `CREATE` 重建關係、保留平行邊；
  非 wipe 走 `MERGE`，同起訖同型別的平行邊會被塌縮。
- 指令會互動詢問是否清空資料庫，輸入 `yes`。
- 還原後應為 2,763 節點／3,803 關係，數量不符會直接報錯。

**驗證狀態：✅ 實機完成**（節點 2763／關係 3803，零失敗）

---

## 3. 檢查環境

```powershell
$env:NEO4J_PASSWORD = '<your-password>'
python tools\check_neo4j_env.py
```

會依序檢查 Java 版本、Bolt 連線、Neo4j 版本、APOC、**GDS 版本配對**、圖譜規模、
`n.type` 屬性與分群覆蓋。全部 PASS 才算就緒。

**驗證狀態：✅ 實機完成**（9 項全 PASS）

---

## 4. 啟動平台

```powershell
# 後端（Flask，預設 127.0.0.1:5000）
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend'
copy .env.example .env      # 填入 NEO4J_* 與你要用的 LLM 供應商金鑰
pip install -r requirements-platform.txt
python app.py

# 前端（Vite，預設 127.0.0.1:3000）
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\frontend'
npm install
npm run dev -- --host 127.0.0.1 --port 3000
```

健檢：`GET http://127.0.0.1:5000/api/overview-stats`
應回 `node_count=2763`、`edge_count=3803`、`community_count=87`、`chapter_count=20`。

「智慧導師」需要 LLM 金鑰；其餘四個頁面只靠 Neo4j 即可運作。

**驗證狀態：✅ 實機完成**（五個頁面均正常）

---

## 5. 重跑實驗

三條路線的成本差很多，依需求選擇。

### 路線 A：只重算分析（不需 LLM）

實驗二的分群、群內中心性與拓樸分層可直接在既有圖上重算：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\exp_2\phase2'
python step2_1_leiden.py            # 參數掃描與 finalize（需要 GDS）
python step2_3_centrality.py        # 群內 degree/betweenness/closeness（預設 min_size=10）
python step2_4_topo_layer.py        # 拓樸分層（Centrality 與 DAG 雙方法）
```

輸出落在 `result/exp2_leiden/`。

**驗證狀態：✅ 實機完成**（step2_3／step2_4 於 2026-08-04 重跑，結果已入庫）

### 路線 B：重跑 Graph RAG 評測（需要 LLM 額度）

見 `CybersecurityLearningPlatform/backend/exp_3/B4_RUNBOOK.md`。
需自備四個受測模型的端點與金鑰，以及**原始題庫**——
本 repo 依著作權考量不散布考題，`result/exp3_graphrag/heldout_question_index.json`
提供題號與原始題庫檔的 SHA-256 供核對。

**驗證狀態：⚠️ 未於本次重跑驗證**（沿用 2026-07-13 的正式跑批結果）

### 路線 C：從教材重跑完整 ETL（需要 LLM 額度與原始教材）

`CybersecurityLearningPlatform/backend/ETL_module/` 內的 `01_chunk_data.py` →
`02_extract_triples.py` → `03_validate_and_import*.py`。
公開包**不含**原始教材 PDF 與其切塊（`Chunks/`），因此路線 C 無法從公開內容完整重現；
可從 `ETL_module/Validated/` 的已驗證三元組重建圖譜（見 `DATA_MANIFEST.md`）。

**驗證狀態：⚠️ 未於本次重跑驗證**

---

## 6. 測試

```powershell
# 後端與實驗程式
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend'
python -m pytest tests/ exp_1/rerun_prep/ exp_2/phase2/tests/ -q

# 發布工具
Set-Location -LiteralPath '..\..'
python -m pytest tools/tests/ -q

# 前端
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\frontend'
npm test
```

**驗證狀態：✅ 實機完成**（後端 87 passed、phase2 13 passed、工具 30 passed、前端 11 passed）

---

## 7. 發布前檢查

```powershell
python tools\check_release_ready.py      # 金鑰樣式、禁止內容、單檔大小
python tools\build_clean_release.py      # 依 allowlist 產出乾淨發布包
```

可公開與不可公開的內容界線見 `DATA_MANIFEST.md`。
