# 資料清單

本文件區分「內部研究工作樹」與「公開交接發布包」。兩者用途不同，不可將內部目錄直接壓縮或推送為公開版本。

## 目錄角色

| 目錄 | 角色 | 發布狀態 |
|---|---|---|
| `論文/交接/` | 內部研究工作樹，保留研究資料、執行產物與本機環境 | **不可直接公開**；可能仍含 `.env`、教材切塊、日誌、快取、備份與依賴目錄 |
| `論文/交接_release/` | 由 allowlist 打包器重建的公開交接發布包 | 通過發布掃描後才可分享或提交 Git |

公開包由下列命令建立；腳本只複製允許清單中的檔案，不會刪除或搬移內部研究工作樹：

```powershell
python tools/build_clean_release.py
python tools/check_release_ready.py --root ..\交接_release
```

## 公開發布包允許內容

| 路徑 | 用途 |
|---|---|
| `platform/backend/ETL_module/RawTriples/` | 萃取階段產生的候選三元組 |
| `platform/backend/ETL_module/Rejected/` | 品質控制分析所需的拒絕三元組與驗證紀錄 |
| `platform/backend/ETL_module/Validated/` | 可用於重建或檢查最終圖譜的已驗證三元組 |
| `platform/backend/exp_1/` | 實驗一：圖譜品質驗證之可公開程式與產物 |
| `platform/backend/exp_2/` | 實驗二：Leiden 分群有效性之可公開程式與產物 |
| `platform/backend/exp_2/phase2/migrate_analysis_properties.py` | 可公開的安全 migration 程式碼；不包含任何實際備份、manifest 或本機連線資訊 |
| `platform/backend/exp_3/` | 實驗三：Graph RAG 事實正確性之可公開程式與產物；正式凍結結果僅供讀取驗證 |
| `platform/backend/prompts/` | 執行所需之 Prompt 模板；不含逐次完整 Prompt／回答日誌 |
| `platform/frontend/` | 前端原始碼、設定與套件鎖定檔 |
| `ontology/` | 實體、關係與合法邊之本體論權威檔案 |
| `docs/prompts/` | 論文方法與附錄使用之 Prompt 說明 |
| `docs/`、根目錄文件與發布工具 | 部署、復現、安全與驗收說明 |

上述目錄仍受打包器的檔名、路徑、副檔名與單檔大小限制；位於允許目錄內不代表所有檔案都會自動公開。

## 公開發布包禁止內容

下列內容可存在於內部研究工作樹，但必須不存在於 `交接_release/`：

| 類別 | 代表路徑或模式 | 原因 |
|---|---|---|
| 環境與秘密值 | `.env`、金鑰、密碼、憑證檔 | 防止憑證外洩；只允許空值或 placeholder 的 `.env.example` |
| 教材原文衍生物 | `backend/ETL_module/Chunks/` | 可能包含受著作權保護之教材切塊 |
| 日誌 | `logs/`、`*.log`、`*_log.txt` | 可能含 Prompt、模型回答、使用者輸入或私有追蹤內容 |
| 依賴與建置產物 | `node_modules/`、`dist/`、`coverage/` | 可由套件鎖定檔與建置命令重建 |
| 快取 | `cache/`、embedding cache、semantic index | 體積大、可重建，且可能夾帶執行內容 |
| 備份與資料庫 dump | `backup`、`neo4j_backup_*`、MatchGPT backups | 可能包含私有資料或完整資料庫狀態 |
| migration 內部證據 | `backend/exp_2/phase2/_migration_output/`、`analysis_properties_before.json`、內部 `analysis/` | 可能包含現行資料庫快照、manifest、本機路徑或操作證據；程式碼與測試另由 allowlist 公開 |
| 本機分析產物 | `graphify-out/`、`.graphifyignore`、`graphify_detect_summary.json` | 僅供內部導覽，且可能過時或含本機路徑 |
| 執行狀態 | `user_progress.json`、`user_mistakes.json` | 本機單一使用者展示資料，不屬於公開研究資料 |
| bytecode 與暫存 | `__pycache__/`、`*.pyc`、`.pytest_cache/`、`*.tmp` | 可重建且無交接價值 |
| Archive | `Archive/` | 混有歷史、取代與待判讀材料；公開包不以其作權威來源 |

## 從已驗證資料重建 Neo4j

公開復現自 `Validated/` 開始，不包含原始 PDF 或 `Chunks/`。這可重建公開的結構化圖譜資料，但不等同於從教材原文重跑完整 ETL。

```powershell
Set-Location -LiteralPath '.\platform\backend\ETL_module'
python 03b_restore_neo4j.py
```

還原腳本會讀取 `.env` 或目前程序的環境變數，並寫入指定 Neo4j。執行前應先確認目標資料庫、建立備份並閱讀腳本提示；公開包不提供真實憑證。

現行內部 Neo4j 的分析欄位已於 run `20260715T165835Z` 完成一次安全 migration：中心性欄位為 2,375 / 2,554，分層欄位為 2,554 / 2,554。這是特定受控資料庫的驗收狀態，不會隨公開包散布；從 `Validated/` 重建新資料庫後，仍須先執行 migration dry-run 並重新核對 coverage，不能沿用本機驗收結論。

## 驗收原則

`RELEASE_BUILD_MANIFEST.json` 記錄 allowlist 打包結果的檔案數、總位元組與排除原因摘要。發布前仍須執行 release checker，門檻為秘密值、禁止路徑、超限大檔與未允許檔案皆為 0；只有實際掃描通過的 `交接_release/` 才能稱為已排除私有內容。
