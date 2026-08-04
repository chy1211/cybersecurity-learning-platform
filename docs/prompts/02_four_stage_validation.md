# 02 四階段品質驗證

- **論文章節**：§參-五.1 三元組品質驗證
- **模型**：`meta/llama-3.1-70b-instruct`（NVIDIA）
- **呼叫參數**：`temperature=0.0`、`max_tokens=8192`、`response_format={"type":"json_object"}`
- **權威執行來源**：
  - `論文\交接\platform\backend\ETL_module\03_validate_and_import_fixed.py`
  - `backend\prompts\etl\validate_system.md`
  - `backend\prompts\etl\validate_class_property.md`
  - `backend\prompts\etl\validate_uri_standardization.md`
  - `backend\prompts\etl\validate_semantic_consistency.md`

正式重跑之順序為 Phase 1 程式化 Schema Edge 檢查，再依序執行 Step 1 類別與屬性對齊、Step 2 URI 標準化及 Step 3 語意一致性。Step 2 以同類別節點之 embedding cosine `>0.80`、每端 top-k 10 形成 Ldr；Step 3 在 URI 標準化後執行。以下四段為實際送入模型之模板形式，JSON 外框已按 Python `.format()` 後的單層大括號顯示。

## 共用 System Prompt

```text
你是一位嚴謹的資安知識圖譜策展人(Knowledge Graph Curator)與本體論維護專家。請嚴格根據規則進行判斷，並僅輸出 JSON 格式。
```

## Step 1 User Prompt：類別與屬性對齊

```text
你是一位嚴謹的資安本體論專家。你的任務是執行「類別與屬性檢查 (Class and Property Alignment)」，確認以下三元組是否完全符合預先定義的類別與屬性清單 (Lc,p)。

### 待檢查三元組：
- 主體 (Subject): {subject_display} (類別: {subject_type})
- 關係 (Relation): {relation}
- 受體 (Object): {object_display} (類別: {object_type})

### 合法清單 Lc,p：
{allowed_list}

### 判斷準則（依序執行）：
1. 清單合法性：主體的類別與受體的類別是否都存在於 Lc,p 的 "Classes" 中？關係是否存在於 "Properties" 中？
2. 語意對齊：每個實體的「名稱」與其被賦予的「類別」是否合理對齊？
3. 同義詞寬容原則：請接受資安領域常見的同義詞、縮寫與翻譯。

### 輸出格式（JSON，思維鏈）：
{
"step_1_list_check": "說明主體類別、受體類別與關係是否皆在 Lc,p 中。",
"step_2_alignment_check": "判斷各實體名稱是否為其類別的合理實例（含同義詞寬容）。",
"response": "correct 或 violation",
"reason": "綜合上述步驟的一句話結論。"
}
```

## Step 2 User Prompt：URI 標準化

```text
你是一位嚴謹的資安本體論專家。你的任務是執行「實體對齊與資源重複檢查 (URI Standardization)」。

### 待檢查三元組：
- 主體 (Subject): {subject_display} (類別: {subject_type})
- 受體 (Object): {object_display} (類別: {object_type})

### 現有近似資源清單 (Ldr)：
{duplicate_resources}

### 資安領域已知同義詞對照範例（若遇到類似以下情況直接判定 duplicate）：
- 惡意程式 ≡ 惡意軟體 ≡ 惡意代碼（均指 malware）
- 漏洞 ≡ 弱點 ≡ 脆弱性（均指 vulnerability）
- SQL Injection ≡ SQL注入 ≡ SQL注入攻擊
- 阻斷服務 ≡ DoS攻擊 ≡ 阻斷服務攻擊
- 加密 ≡ 資料加密（作為動詞/技術時）
- 身分驗證 ≡ 認證 ≡ 身份認證

### 禁止合併的母類/子類與易混淆概念範例（遇到類似情況一律判定 correct、禁止合併）：
- 任意存取控制、強制存取控制 ≠ 存取控制（具體模型 vs 母類）
- 網路型入侵偵測系統、主機型入侵偵測系統 ≠ 入侵偵測系統（子類型 vs 母類）
- DDoS ≠ DoS（DDoS 是 DoS 的子類型）
- 線上式UPS ≠ UPS（子類型 vs 母類）
- 作業系統 ≠ 系統；資訊安全風險 ≠ 風險（具體概念 vs 泛稱，一律保留原名）
- Authentication（認證）≠ Authorization（授權）（兩個不同的資安概念，絕非同義詞）

### 判斷準則（依序執行）：
1. 【前提確認】：若 Ldr 為空，或實體名稱與 Ldr 中某資源的 name 字串完全相同，直接判定 correct。
2. 【同義詞判定】：參考上方對照表；或兩個實體在資安教材中可互換使用、指稱同一概念（如同一英文術語的不同中文譯名），判定為 duplicate。
3. 【廣義/狹義一律保留】：若一個實體是另一個的子類型（例如「木馬程式」是「惡意程式」的子集；「Web攻擊」是「攻擊」的子集），判定為 correct，禁止合併。
4. 【不確定時預設保留】：若無法確定，預設 correct。

### 輸出格式（JSON，思維鏈）：
{
"granularity_analysis": "說明與 Ldr 最相似候選的關係：完全等價同義詞、廣義/狹義從屬、還是不相關？",
"response": "duplicate 或 correct",
"standard_subject": "僅當 response 為 duplicate 且主體為同義詞重複時，填入 Ldr 中對應的 name；response 為 correct 時此欄必須為空字串。",
"standard_object": "僅當 response 為 duplicate 且受體為同義詞重複時，填入 Ldr 中對應的 name；response 為 correct 時此欄必須為空字串。",
"reason": "一句話簡潔總結判定依據。"
}
```

## Step 3 User Prompt：語意一致性

```text
你是一位嚴謹的資安本體論專家。你的任務是執行「語義一致性檢查 (Semantic Consistency)」，判斷以下三元組（已完成 URI 標準化）是否違反語義限制清單 (Lsr) 中的任何規則。

### 待檢查三元組（URI 標準化後）：
- 主體: {subject_display} (類別: {subject_type})
- 關係: {relation}
- 受體: {object_display} (類別: {object_type})

### 語義限制清單 (Lsr)：
{semantic_rules}

### 驗證邏輯：
1. 遵守即合法：若三元組符合規則所允許的條件，代表合法，絕對不可判定為違規。
2. 無罪推定：若未發現「明確且直接」的違反項目，response 必須為 correct。

### 輸出格式（JSON，思維鏈）：
{
"step_1_rule_matching": "針對每條相關規則的說明，整合為單一字串。此欄位必須是字串，禁止使用 JSON 陣列。",
"response": "correct 或 violation",
"reason": "最終判定理由（不超過兩句話）。"
}
```

## 執行期變數

- `{subject_display}`、`{subject_type}`、`{relation}`、`{object_display}`、`{object_type}`：待驗證三元組欄位。
- `{allowed_list}`：15 類實體與 16 種關係之合法清單。
- `{duplicate_resources}`：Step 2 的 Ldr 候選陣列，含 `name`、`type`、`similarity_score`。
- `{semantic_rules}`：Step 3 的 Lsr 規則清單。
