# 資料清單

本文件說明交接包收錄哪些資料產物，以及各項資料被收錄或排除的原因。

## 已收錄

| 路徑 | 是否收錄 | 用途 |
|---|---:|---|
| `CybersecurityLearningPlatform/backend/ETL_module/RawTriples/` | 是 | 萃取階段產生的候選三元組 |
| `CybersecurityLearningPlatform/backend/ETL_module/Rejected/` | 是 | 圖譜品質控制分析所需的拒絕三元組與驗證紀錄 |
| `CybersecurityLearningPlatform/backend/ETL_module/Validated/` | 是 | 可用於重建或檢查最終圖譜的已驗證三元組 |
| `CybersecurityLearningPlatform/backend/ETL_module/gamma實驗` | 是 | Leiden gamma 參數掃描證據 |
| `CybersecurityLearningPlatform/backend/ETL_module/minCommunitySize實驗` | 是 | Leiden 最小社群大小參數掃描證據 |
| `CybersecurityLearningPlatform/backend/exp_1/` | 是 | 實驗 1 圖譜品質驗證材料 |
| `CybersecurityLearningPlatform/backend/exp_2/` | 是 | 實驗 2 Leiden 分群有效性驗證材料 |
| `CybersecurityLearningPlatform/backend/exp_3/` | 是 | 實驗 3 Graph RAG 事實正確性評估材料 |
| `CybersecurityLearningPlatform/backend/exp_1/MatchGPT/` | 是 | MatchGPT 節點整併腳本與支援輸出 |
| `本體論/` | 是 | 實體、關係與合法邊的本體論權威檔案 |
| `Prompt/` | 是 | 供方法透明度與附錄整理使用的 Prompt 說明文件 |

## 已排除

| 路徑 | 是否排除 | 原因 |
|---|---:|---|
| `CybersecurityLearningPlatform/backend/ETL_module/Chunks/` | 是 | 可能包含受著作權保護教材的原文切塊 |
| `CybersecurityLearningPlatform/backend/ETL_module/embedding_cache.json` | 是 | 大型產生式快取；GitHub 部署不需要 |
| `CybersecurityLearningPlatform/backend/ETL_module/neo4j_backup_*.json` | 是 | 大型備份；公開 repo 應改用文件化的匯入流程 |
| `CybersecurityLearningPlatform/backend/logs/` | 是 | 本機執行日誌可能包含 Prompt、輸出或私有追蹤內容 |
| `CybersecurityLearningPlatform/frontend/node_modules/` | 是 | 可透過 `npm install` 重建 |
| `CybersecurityLearningPlatform/frontend/dist/` | 是 | 可透過 `npm run build` 重建 |

## 由已收錄檔案重建 Neo4j

公開復現路徑預期從 `Validated/` 開始，而不是從 `Chunks/` 開始。

使用方式：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\ETL_module'
python 03b_restore_neo4j.py
```

還原腳本需要可連線的 Neo4j 實例，並會從 `CybersecurityLearningPlatform\backend\.env` 或目前環境變數讀取有效憑證。確認寫入資料庫前，請先閱讀腳本提示。

## 完整端到端 ETL

若要從 PDF 重新建圖，需要原始教材文件與 `Chunks/`。這些內容未納入此 GitHub 交接包，原因是著作權與 repository 體積控管。
