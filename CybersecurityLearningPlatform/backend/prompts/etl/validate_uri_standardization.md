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
- 防火牆 ≡ 網路防火牆
- 身分驗證 ≡ 認證 ≡ 身份認證

### 判斷準則（依序執行）：
1. 【前提確認】：若 Ldr 為空，或實體名稱與 Ldr 中某資源的 name 字串完全相同，直接判定 correct。
2. 【同義詞判定】：參考上方對照表；或兩個實體在資安教材中可互換使用、指稱同一概念（如同一英文術語的不同中文譯名），判定為 duplicate。
3. 【廣義/狹義一律保留】：若一個實體是另一個的子類型（例如「木馬程式」是「惡意程式」的子集；「Web攻擊」是「攻擊」的子集），判定為 correct，禁止合併。
4. 【不確定時預設保留】：若無法確定，預設 correct。

### 輸出格式（JSON，思維鏈）：
{{
"granularity_analysis": "說明與 Ldr 最相似候選的關係：完全等價同義詞、廣義/狹義從屬、還是不相關？",
"response": "duplicate 或 correct",
"standard_subject": "若主體為同義詞重複，填入 Ldr 中對應的 name；否則留空字串。",
"standard_object": "若受體為同義詞重複，填入 Ldr 中對應的 name；否則留空字串。",
"reason": "一句話簡潔總結判定依據。"
}}
