# 執行期 Prompt 庫

本資料夾是後端服務與實驗腳本實際載入的 runtime prompt 來源。

程式碼應呼叫 `prompts.load_prompt("relative/path.md")`，而不是在 `.py` 檔中內嵌長 prompt 字串。研究方法與附錄導向的說明文件放在交接根目錄的 `Prompt/`；可執行的 prompt 模板則保留在本資料夾。

目前分組：

- `platform/`：Flask 平台端 LLM 功能，例如測驗生成、Graph RAG 回答與錯題解釋。
- `etl/`：三元組萃取與驗證 prompt。
- `matchgpt/`：節點整併判斷 prompt。
- `exp_3/`：Graph RAG 評估、NF1 檢索與少樣本範例。

若變更 prompt 檔名或模板變數，請執行：

```powershell
python -m unittest discover -s ".\tests" -t "." -p "test_prompt*.py" -v
```
