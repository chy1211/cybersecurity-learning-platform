# 論文提示詞彙整

> 本資料夾彙整實際使用之 LLM 提示詞，依論文章節與處理階段分檔整理。
>
> 各提示詞內容皆**逐字取自現行程式碼**，並標註對應論文章節、所用模型與參數、變數佔位符說明與來源檔案，供重現實驗使用。
>
> **最後整理：2026-07-14**（五支實驗提示詞已依最後一次 ETL／B4 正式執行之 runtime 來源逐項核對）


---

## 一、檔案索引與論文章節對照

### 核心方法（第參章）

| 檔案 | 提示詞 | 論文章節 | 模型 |
|------|--------|----------|------|
| [`01_知識萃取_三元組擷取.md`](01_知識萃取_三元組擷取.md) | 教材／考題分流之本體論三元組萃取 | §參-四 ETL 管線與知識萃取 | `gemma-4-31b-it` |
| [`02_四階段品質驗證.md`](02_四階段品質驗證.md) | 共用系統提示詞＋Step 1 類別屬性對齊＋Step 2 URI 標準化＋Step 3 語意一致性 | §參-五.1 三元組品質驗證 | Llama-3.1-70B-Instruct |
| [`03_MatchGPT節點整併.md`](03_MatchGPT節點整併.md) | 全圖同義節點整併判定 | §參-五.2 MatchGPT 節點整併模組 | Llama-3.1-70B-Instruct |
| [`04_GraphRAG知識輔助問答.md`](04_GraphRAG知識輔助問答.md) | 基於知識圖譜子圖脈絡之問答 | §參-七 知識輔助問答設計 | 平台端可切換 |

### 評估實驗（§參-八／第肆章）

| 檔案 | 提示詞 | 論文章節 | 模型 |
|------|--------|----------|------|
| [`05_實驗3_GraphRAG事實正確性作答.md`](05_實驗3_GraphRAG事實正確性作答.md) | 正式 `base`／`rag` 共用 System 與 User Prompt；僅 evidence set 不同 | 評估實驗三：Graph RAG 事實正確性 | `gemma-4-e4b-it`／`openai/gpt-oss-20b`／`meta/llama-3.1-70b-instruct`／`google/gemma-4-31b-it` |
| [`06_實驗3_NF1子圖檢索.md`](06_實驗3_NF1子圖檢索.md) | B4 route 2：完整題目分解、受測模型在環實體連結、關係選擇與二跳子圖擷取 | 評估實驗三：逐模型子圖檢索 | 同上（per-model） |

### 平台應用功能（第肆章）

> 以下屬應用層之下游 LLM 功能，論文於第肆章作為「平台實作功能」帶過，**不納入第參章驗證論述範圍**（依論文研究範圍界定）。整理於此以求完整。

| 檔案 | 提示詞 | 對應 API | 模型 |
|------|--------|----------|------|
| [`07_平台應用_錯題解釋.md`](07_平台應用_錯題解釋.md) | 答錯後概念釐清解析 | `POST /api/mistakes/explain` | 平台端可切換 |
| [`08_平台應用_測驗生成.md`](08_平台應用_測驗生成.md) | 單主題出題＋多主題批量出題 | `POST /api/quiz/generate` | 平台端可切換 |
| [`09_平台應用_查詢意圖與實體提取.md`](09_平台應用_查詢意圖與實體提取.md) | 查詢術語識別＋文字實體關係提取 | `POST /api/chat`（fallback）／內部 | 平台端可切換 |

---

## 二、模型與環境摘要

- **知識萃取階段**：固定使用 `gemma-4-31b-it`（Google GenAI SDK，`thinking_level="high"`，temperature=0.1）。
- **四階段驗證階段**：固定使用 `meta/llama-3.1-70b-instruct`（NVIDIA，temperature=0.0，`response_format=json_object`）。
- **MatchGPT 整併**：`meta/llama-3.1-70b-instruct`；blocking 用 `text-embedding-embeddinggemma-300m-qat`（cosine 閾值 0.80、top-k=10）；最終以 confidence 門檻 t=0.7 定案。
- **平台端（`llm_service.py`）**：支援 NVIDIA／Groq／LM Studio／OpenAI 四種 provider 切換（由 `LLM_PROVIDER` 環境變數控制），論文示範以 Llama-3.3-70b-instruct 為主。
- **實驗 3**：356 題單選；正式執行期 model id 為 `gemma-4-e4b-it`、`openai/gpt-oss-20b`、`meta/llama-3.1-70b-instruct`、`google/gemma-4-31b-it`，條件為 `base` 與 `rag`。每個模型各自完成 route-2 實體連結、關係選擇與子圖檢索。

---

## 三、變數佔位符通則

各檔案提示詞中以大括號 `{...}` 或角括號 `<<<<...>>>>` 標示之欄位為執行期填入之變數，常見者：

- `{chunk_text}`：教材切塊後之單一文本片段。
- `{subject_display}`／`{subject_type}`／`{relation}`／`{object_display}`／`{object_type}`：四階段驗證之待驗證三元組欄位。
- `{allowed_list}`／`{duplicate_resources}`／`{semantic_rules}`：Step 1 合法清單、Step 2 近似資源候選及 Step 3 語意限制規則。
- `{type_a}`／`{type_def}`／`{name_a}`／`{name_b}`：MatchGPT 同類別候選節點之類別、定義與名稱。
- `{stem}`／`{options}`／`{evidence_block}`：正式 B4 作答之題幹、A–D 選項與證據集合；`base` 的證據固定為空陣列。
- `{context}`：由 Neo4j 取得並組裝之知識圖譜子圖脈絡。
- `<<<<QUESTION_JSON>>>>`／`<<<<MENTIONS_JSON>>>>`：B4 route-2 之完整題目 JSON 與受限候選實體連結輸入。
- `<<<<SENTENCE>>>>`／`<<<<RELATION_SET>>>>`／`<<<<TOP_K>>>>`：B4 route-2 之子主張、候選關係集合與關係選取數。

---

## 四、來源與說明

- 本資料夾為研究呈現用鏡像；可執行提示詞的**單一權威來源**為 `論文\交接\CybersecurityLearningPlatform\backend\prompts\` 與載入該模板的 ETL／B4 程式。若本資料夾與 runtime 來源有差異，以最後正式執行所載入的 runtime 來源為準。
- 知識萃取與 NF1 檢索之提示詞設計分別參酌 Xu et al. (2024)／Huang & Xiao (2024) 之 LLM 資訊萃取，以及 Kim et al. (2023) 之 KG-GPT；MatchGPT 整併參酌 Peeters & Bizer (2023)；四階段驗證參酌 Regino & dos Reis (2025)。各檔案內另有逐項對應說明。
