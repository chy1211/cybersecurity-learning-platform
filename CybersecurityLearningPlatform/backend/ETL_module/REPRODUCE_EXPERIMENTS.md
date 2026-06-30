# 實驗復現說明

本交接包支援從結構化中間產物復現，而不是從原始 PDF 教材切塊重新開始。

## 前置需求

- Windows PowerShell 或相容 shell。
- Python 3.13 或相容 Python 3 環境。
- 前端需 Node.js 與 npm。
- 本機需執行 Neo4j，並啟用 Bolt 連線。
- 需依相關 `requirements.txt` 安裝 Python 依賴。
- 視重跑腳本而定，可能需要 LLM provider 憑證。

## 1. 準備後端環境

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend'
Copy-Item .env.example .env
```

編輯 `.env`：

- 設定 `NEO4J_PASSWORD`。
- 選擇 `LLM_PROVIDER`。
- 設定所選 provider 的憑證；或使用 `lm_studio` 搭配本機 OpenAI-compatible server。

安裝後端依賴：

```powershell
python -m pip install -r requirements.txt
```

## 2. 將已驗證三元組還原至 Neo4j

公開交接包已收錄 `Validated/`，因此可在沒有原始教材切塊的情況下重建 Neo4j 圖譜。

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\ETL_module'
python 03b_restore_neo4j.py
```

確認寫入資料庫前，請仔細閱讀腳本提示。

## 3. 啟動平台

後端：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend'
python app.py
```

前端：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\frontend'
npm install
npm run dev
```

## 4. 檢查 ETL 品質產物

已收錄資料夾：

- `RawTriples/`：萃取出的候選三元組。
- `Rejected/`：被拒絕的三元組與驗證輸出。
- `Validated/`：通過驗證、可匯入 Neo4j 的三元組。

常用腳本：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\ETL_module'
python 04_count_raw_triples_stats.py
python 03c_analyze_validated_changes.py
python 03d_deep_analysis.py
```

部分腳本可能預期原始本機目錄結構或可連線的 Neo4j 實例。若腳本因缺少 `Chunks/` 而失敗，請改用已收錄的 `RawTriples/`、`Rejected/` 與 `Validated/` 進行檢查，不要從 PDF 重跑。

## 5. 實驗資料夾

| 實驗 | 路徑 | 用途 |
|---|---|---|
| 1 | `CybersecurityLearningPlatform/backend/exp_1/` | 圖譜品質驗證 |
| 2 | `CybersecurityLearningPlatform/backend/exp_2/` | Leiden 分群有效性驗證 |
| 3 | `CybersecurityLearningPlatform/backend/exp_3/` | Graph RAG 事實正確性評估 |

各資料夾可能包含論文實驗腳本、輸出與中間檔。建議先閱讀該資料夾內的 README（若存在），再檢查腳本名稱與 JSON/CSV 輸出檔。
