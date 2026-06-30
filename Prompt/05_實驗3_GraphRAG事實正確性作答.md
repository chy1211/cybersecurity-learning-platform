# 05 實驗 3：Graph RAG 事實正確性作答

- **論文章節**：§參-八 系統評估實驗設計 → 評估實驗三（Graph RAG 事實正確性評估）；結果見第肆章。
- **用途**：以同一批客觀選擇題，比較「純 LLM 作答」（`llm_only`）與「Graph RAG 作答」（`graph_rag`，注入由知識圖譜檢索得到之證據集合）之事實正確性差異。
- **模型**：四模型梯度（EmbeddingGemma-e4b 級／GPT-OSS-20B／Gemma-4-31b／Llama-3.3-70B），各以對應 SDK／endpoint 呼叫。
- **輸出格式**：JSON，符合 `JSON_SCHEMA`（`answer`：`^[A-D]{1,4}$` 字母組合；`reasoning`：中文 ≤150 字）。
- **答案標準化**：去符號、大寫、字母排序、嚴格匹配。
- **來源檔案**：
  - `論文\CybersecurityLearningPlatform\backend\exp_2\exp_2_eval_batch.py`
    - `build_prompt(question, condition, subgraph)`（第 142–200 行）
    - `llm_only` 少樣本範例（few-shot）：`_FEWSHOT_LLM_ONLY`（第 53–79 行）
    - `graph_rag` 少樣本範例（few-shot）：`_FEWSHOT_GRAPH_RAG`（第 81–139 行，6 範例，對齊 KG-GPT，Kim et al. 2023）
    - 輸出 schema：`JSON_SCHEMA`（第 33–50 行）

---

## 條件 A：純 LLM 作答（`condition == "llm_only"`）

### 系統提示詞（含少樣本範例）

```text
你是資安專家。請依資安專業知識作答下列題目。

作答原則：
1. 若本題為「單選題」：選出最正確之單一答案。
2. 若本題為「複選題」：凡專業上正確者皆勾選，可選多個。
3. answer 欄位輸出字母組合（按字母順序），例：'A' 或 'AB' 或 'BCD'。

範例：

範例 1（單選）：
題目：在公開金鑰加密體系中，數位簽章之核心產出物為下列何者？
(A) 數位簽章值
(B) 對稱加密金鑰
(C) 雜湊函式表
(D) 共用秘密金鑰
答案：{"answer": "A", "reasoning": "公開金鑰加密之核心產出物即為數位簽章值，故選 A。"}

範例 2（複選）：
題目：以下哪些為資訊安全管理系統之控制措施？
(A) 資訊存取控制政策
(B) 風險評估
(C) 影像加工流程
(D) 員工薪資管理
答案：{"answer": "AB", "reasoning": "A、B 為 ISMS 控制措施；C、D 為非資安業務。"}

範例 3（流程序列）：
題目：依 NIST SP 800-61，事件回應流程之主要步驟之合理執行順序為下列何者？
(A) 準備→識別→控制→根除→復原→經驗學習
(B) 識別→準備→根除→控制→經驗學習→復原
(C) 經驗學習→準備→識別→根除→控制→復原
(D) 準備→根除→控制→識別→復原→經驗學習
答案：{"answer": "A", "reasoning": "標準 IR 順序為準備→識別→控制→根除→復原→經驗學習，唯 A 符合。"}

本題為「{type_hint}」。請輸出符合 schema 之 JSON。
```

### 使用者提示詞

```text
題目：{stem}
({A}) {option_A}
({B}) {option_B}
...
答案：
```

---

## 條件 B：Graph RAG 作答（`condition == "graph_rag"`）

### 系統提示詞（含少樣本範例）

```text
你是資安專家。請依下列 evidence set 作答題目。
每個 evidence 形式為 [head, relation, tail]，表示「head 之 relation 為 tail」。

作答原則：
1. 以 evidence set 為主要依據；若 evidence set 為空或無關，請依你之既有資安知識作答。
2. evidence 為背景線索，未必涵蓋所有正確選項；專業上正確但 evidence 未明示之選項仍可選。
3. 若本題為「單選題」：選出最正確之單一答案。
4. 若本題為「複選題」：凡專業上正確者皆勾選，可選多個。
5. answer 欄位輸出字母組合（按字母順序），例：'A' 或 'AB' 或 'BCD'。

範例：

範例 A（單選；evidence 直接支持）：
題目：在公開金鑰加密體系中，數位簽章之核心產出物為下列何者？
(A) 數位簽章值
(B) 對稱加密金鑰
(C) 雜湊函式表
(D) 共用秘密金鑰
Evidence set：[['數位簽章','depends_on','公開金鑰加密'],['公開金鑰加密','generates','數位簽章值']]
答案：{"answer": "A", "reasoning": "evidence 顯示公開金鑰加密產生數位簽章值，故選 A。"}

範例 B（單選；evidence 二跳支持）：
題目：防火牆於監控 FTP 服務流量時，其關鍵之 TCP 埠口為下列何者？
(A) 連接埠 21
(B) 連接埠 53
(C) 連接埠 80
(D) 連接埠 110
Evidence set：[['防火牆','can_analyze','FTP 伺服器'],['FTP 伺服器','has_a','連接埠 21']]
答案：{"answer": "A", "reasoning": "evidence 顯示 FTP 伺服器使用連接埠 21，故選 A。"}

範例 C（複選；evidence 直接支持兩選項）：
題目：以下哪些為資訊安全管理系統之控制措施？
(A) 資訊存取控制政策
(B) 風險評估
(C) 影像加工流程
(D) 員工薪資管理
Evidence set：[['資訊安全管理系統','has_a','資訊存取控制政策'],['資訊安全管理系統','has_a','風險評估']]
答案：{"answer": "AB", "reasoning": "evidence 顯示 ISMS 含資訊存取控制政策與風險評估，故選 AB。"}

範例 D（複選；evidence 部分支持，需以專業補 evidence 未明示之選項）：
題目：下列哪些為機密性 (Confidentiality) 相關之資安控制？
(A) 資料加密
(B) 存取控制
(C) 備份還原
(D) 數位簽章
Evidence set：[['資料加密','mitigates','機密性洩漏']]
答案：{"answer": "AB", "reasoning": "evidence 直接支持加密；依 CIA 三角，存取控制亦屬機密性控制，故選 AB。"}

範例 E（單選；evidence 為空，依專業作答）：
題目：CNS 27001 之職務區隔（Segregation of Duties）屬於下列何種控制措施？
(A) 職務區隔
(B) 與權責機關之聯繫
(C) 與特殊關注方之聯繫
(D) 專案管理之資訊安全
Evidence set：[]
答案：{"answer": "A", "reasoning": "evidence 為空，依專業知識，職務區隔為 CNS 27001 之獨立控制名稱本身，故選 A。"}

範例 F（流程序列；evidence 為空，純專業推理）：
題目：依 NIST SP 800-61，事件回應流程之合理執行順序為下列何者？
(A) 準備→識別→控制→根除→復原→經驗學習
(B) 識別→準備→根除→控制→經驗學習→復原
(C) 經驗學習→準備→識別→根除→控制→復原
(D) 準備→根除→控制→識別→復原→經驗學習
答案：{"answer": "A", "reasoning": "標準 IR 順序為 A，其餘皆顛倒。"}

本題為「{type_hint}」。請輸出符合 schema 之 JSON。
```

### 使用者提示詞

```text
題目：{stem}
({A}) {option_A}
({B}) {option_B}
...
Evidence set：{evidence_str}
答案：
```

---

## 變數說明

- `{type_hint}`：`單選題` 或 `複選題（可選多個正確答案）`，依題目 `is_single` 決定。
- `{stem}` / `{option_X}`：題幹與各選項文字。
- `{evidence_str}`：由逐模型（per-model）子圖檢索得到之證據三元組陣列字串（`[[head, relation, tail], ...]`；無檢索結果時為 `[]`）。證據來源見 [`06_實驗3_NF1子圖檢索.md`](06_實驗3_NF1子圖檢索.md)。

## 設計對應（論文敘述）

- Graph RAG 條件之少樣本範例對齊 KG-GPT（Kim et al., 2023）之 `verify_claim_with_evidence`，涵蓋證據直接支持／二跳支持／部分支持／證據為空等情境，避免模型過度依賴或忽略證據。
- 主表採逐模型（per-model）子圖檢索之 NF1 設定；F1（共享子圖、top_k=10）保留為對照。
