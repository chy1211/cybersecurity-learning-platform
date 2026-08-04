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
{{
"granularity_analysis": "說明與 Ldr 最相似候選的關係：完全等價同義詞、廣義/狹義從屬、還是不相關？",
"response": "duplicate 或 correct",
"standard_subject": "僅當 response 為 duplicate 且主體為同義詞重複時，填入 Ldr 中對應的 name；response 為 correct 時此欄必須為空字串。",
"standard_object": "僅當 response 為 duplicate 且受體為同義詞重複時，填入 Ldr 中對應的 name；response 為 correct 時此欄必須為空字串。",
"reason": "一句話簡潔總結判定依據。"
}}
