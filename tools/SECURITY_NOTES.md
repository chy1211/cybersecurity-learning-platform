# 安全與發布注意事項

此交接包以 GitHub 發布為目標整理。請預設其內容可能公開。

## 憑證

不應提交任何真實憑證。

已清理後的後端設定只會從環境變數讀取 provider 憑證：

- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `GROQ_API_KEY_1`
- `GROQ_API_KEY_2`
- `NVIDIA_API_KEY_1` 至 `NVIDIA_API_KEY_6`
- `NEO4J_PASSWORD`

非機密連線設定也由環境變數讀取：

- `NEO4J_URI`
- `NEO4J_USER`
- `LM_STUDIO_BASE_URL`
- `LM_STUDIO_CHAT_URL`
- `LM_STUDIO_CHAT_URL_ALT`
- `EMBEDDING_BASE_URL`

`CybersecurityLearningPlatform/backend/.env.example` 可安全提交，因為所有憑證欄位皆為空白佔位符。

## 刻意排除的檔案

| 排除項目 | 原因 |
|---|---|
| `backend/.env` | 本機機密設定 |
| `backend/logs/` | 執行期 Prompt 與 LLM 回應可能包含敏感本機追蹤內容 |
| `frontend/node_modules/` | 可重建的依賴輸出 |
| `frontend/dist/` | 建置輸出 |
| `__pycache__/`、`*.pyc` | Python 產生檔 |
| `backend/user_progress.json` | 本機使用者狀態 |
| `backend/user_mistakes.json` | 本機使用者狀態與可能的個人追蹤內容 |
| `backend/ETL_module/Chunks/` | 可能包含受著作權保護教材的原文切塊 |
| `backend/ETL_module/embedding_cache.json` | 大型產生式快取 |
| `backend/ETL_module/neo4j_backup_*.json` | 大型本機備份，可能重複完整圖譜資料 |
| 平台樹中的 `*.pdf` | 下載的參考文獻或來源 PDF 不需要用於公開部署 |

## 發布前檢查

推送前請執行 release checker。它會掃描可能的憑證模式，但不會印出秘密值：

```powershell
python tools/check_release_ready.py
```

預期結果為 `PASS`。若出現 `SECRET_LIKE_VALUE` 或 `LOCAL_ABSOLUTE_PATH`，發布前必須逐項檢查。
