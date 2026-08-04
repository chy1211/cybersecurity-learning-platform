# 05 實驗三：Graph RAG 事實正確性作答

- **論文章節**：§參-八 評估實驗三；結果見第肆章
- **正式條件名稱**：`base` 與 `rag`
- **正式範圍**：356 題單選；兩條件使用完全相同的 System／User Prompt，僅 `evidence_block` 內容不同。
- **受測模型與執行期 model id**：
  - `e4b` → `gemma-4-e4b-it`
  - `gptoss` → `openai/gpt-oss-20b`
  - `llama70b` → `meta/llama-3.1-70b-instruct`
  - `gemma31b` → `google/gemma-4-31b-it`
- **權威執行來源**：
  - `論文\交接\platform\backend\exp_3\exp_3_eval_batch.py`
  - `backend\prompts\exp_3\b4_eval_system.md`
  - `backend\prompts\exp_3\graph_rag_fewshot.md`
  - `backend\prompts\exp_3\eval_user.md`

> 下列 System Prompt 已將執行時載入的 `graph_rag_fewshot.md` 完整展開，不保留中介佔位；這正是最後一次正式 B4 作答時 `base` 與 `rag` 共用的訊息內容。

## 正式 B4 System Prompt（few-shot 已展開）

```text
你是資安專家。請完成下列單選題，並在 evidence set 有相關內容時優先參考。

作答原則：
1. evidence set 是可稽核的背景證據；若為空或不足，仍可依資安專業知識作答。
2. 不要把 evidence set 中沒有的關係當成已被證明的事實。
3. 本題為單選題，只選出一個最正確答案。
4. answer 欄位只能輸出一個 A、B、C 或 D。

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
Evidence set：[]
答案：{"answer": "A", "reasoning": "標準 IR 順序為 A，其餘皆顛倒。"}

請輸出符合 schema 的 JSON。
```

## 正式 B4 User Prompt 模板

```text
題目：{stem}
{options}
{evidence_block}答案：
```

執行時替換規則如下：

- `{stem}`：該題題幹。
- `{options}`：依 A、B、C、D 順序組成 `(A) 選項文字` 等四行。
- `{evidence_block}`：`base` 固定為 `Evidence set：[]\n`；`rag` 為 `Evidence set：[[head, relation, tail], ...]\n`。若 RAG 未檢索到證據，其內容同樣為空陣列。
- 正確答案與題目 rationale 不會進入 Prompt。

## 正式輸出 JSON Schema

```json
{
  "type": "object",
  "properties": {
    "answer": {
      "type": "string",
      "pattern": "^[A-D]{1,4}$",
      "description": "答案字母組合（單選一個、複選多個按字母順序），例：'A' 或 'BCD'"
    },
    "reasoning": {
      "type": "string",
      "minLength": 5,
      "maxLength": 500,
      "description": "作答理由（中文，≤150 字）"
    }
  },
  "required": ["answer", "reasoning"],
  "additionalProperties": false
}
```

正式評分集雖沿用可容納歷史複選輸出的 schema 形狀，實際輸入與 System Prompt 均限定單選，答案以單一 A、B、C 或 D 嚴格匹配。
