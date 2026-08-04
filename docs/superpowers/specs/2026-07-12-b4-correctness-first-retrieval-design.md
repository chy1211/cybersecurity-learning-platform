# B4 Graph RAG 正確性優先：題庫正規化與實體連結設計

> 狀態：**已核准的部分設計；尚未進入實作，B4 仍禁止開跑。**
>
> 核准日期：2026-07-12
>
> 核准者：使用者（詹皇羿）
>
> 主要讀者：後續接手 B4 的 Codex／Claude Session

## 1. 一句話摘要

B4 不再要求與舊 NF1 方法可比；新設計以科學正確性與可稽核性為最高優先。正式文字型留測集排除 8 題缺少附圖的題目，分母由 364 改為 356；檢索輸入改為題幹加全部選項並保存來源；實體連結改為「正規化精確匹配 → 經審核別名 → 有門檻的語意候選」，無法可靠判斷時必須回報 `unresolved`，禁止使用原本無排序的雙向 `CONTAINS + LIMIT 1` 任選節點。

## 2. 本文件的權威範圍

本文件只鎖定以下已獲使用者核准的部分：

1. 正確性優先，不保留舊 NF1 方法可比性。
2. 排除 8 題缺少必要圖片的題目，正式分母為 356。
3. 檢索必須讀取題幹與 A–D 全部選項，並保存每個 mention 的來源。
4. 最終作答仍為一次四選一相對比較，不採逐選項 True/False 或四組 `is_correct` JSON。
5. 實體連結採 precision-first；沒有足夠證據時寧可 `unresolved`，不可任選節點。
6. 所有門檻只准用建構集校準；正式留測集凍結後不得回頭調整。

本文件**尚未授權**直接修改程式或啟動任何模型。關係選擇、子圖展開、evidence 排序、最終作答 Prompt、完整錯誤閘門等後續設計仍須逐項拍板；詳見第 12 節。

## 3. 為什麼要取代原方法

### 3.1 題庫介面目前無法直接執行

權威留測來源為：

`F:\temp\AgentWorkBase\_tooling\rerun_out\heldout_test_set_scoped.json`

實際資料有兩種 schema：

- 36 題 ITE／ISN 使用 `qid`、`is_single`。
- 328 題 iPAS 使用 `id`、`qtype`。

現行 `exp_3_nf1_pipeline.py` 與 `exp_3_eval_batch.py` 直接存取 `q["qid"]`，因此全量會在第一筆 iPAS 題目失敗；只跑前 5 題會因前五題均為 ISN 而形成假性通過。

### 3.2 八題的原始 PDF 有圖，但評測輸入沒有圖

排除清單固定如下：

1. `ISN-107-012`：網址列／憑證警告畫面。
2. `ISN-107-021`：伺服器系統紀錄截圖。
3. `ISN-107-022`：組織連外流量圖。
4. `IPAS-110-TEC-054`：登入頁面驗證圖片／CAPTCHA。
5. `IPAS-111-MGT-082`：密碼安全措施編號圖。
6. `IPAS-111-MGT-089`：Kerberos 認證流程圖。
7. `IPAS-113-MGT-021`：風險回應方式編號圖。
8. `IPAS-113-MGT-030`：生物辨識誤差指標圖。

原始 PDF 的相關頁面已確認含圖片物件。缺口發生在題庫抽取：iPAS 只以 `pdfplumber.page.extract_text()` 保存文字；ITE 舊題庫同樣沒有圖片路徑或裁切資訊。四個受測模型的多模態能力不同，補傳圖片會引入新的模型能力差異；人工轉寫圖片則會引入研究者解讀。因此正式文字型評測排除這 8 題。

### 3.3 原實體匹配會把錯誤節點當成成功

現行 Cypher 為：

```cypher
MATCH (n:KGNode)
WHERE toLower(n.name) = toLower($name)
   OR toLower(n.name) CONTAINS toLower($name)
   OR toLower($name) CONTAINS toLower(n.name)
RETURN elementId(n) AS id, n.name AS name
LIMIT 1
```

此查詢沒有 exact-first 排序，也沒有長度、歧義或信心門檻。現場實測包含：

- `SQL Injection` 選到 `sql`。
- `防火牆` 有 9 個候選，選到 `防火牆過濾功能`。
- `系統` 有 136 個候選，選到 `資訊系統管理`。
- `資料` 有 137 個候選。
- `s` 有 280 個候選。

所以「子圖非空」不等於「子圖正確」。新方法必須同時記錄連結依據與拒絕原因。

## 4. 核心設計原則

### 4.1 原始資料不可變

不得覆寫 `heldout_test_set_scoped.json`。所有正規化、排除與衍生檔一律寫到新目錄：

`F:\temp\AgentWorkBase\_tooling\rerun_out\b4_graph_rag\input\`

預定產物契約：

- `heldout_test_set_b4_356.json`：正式 356 題正規化留測集。
- `excluded_visual_questions.json`：8 題排除清單、來源與理由。
- `normalization_report.json`：輸入／輸出基數、schema 轉換與驗證結果。
- `heldout_test_set_b4_smoke.json`：正式小樣本檔；不得用 `--limit 5` 代替。

### 4.2 正式考題與建構集職責分離

- 854 題建構集：可用於 alias 建立、語意門檻校準與離線測試。
- 356 題正式留測集：只在方法、門檻與設定全部凍結後執行；不得用正式答案調整任何檢索規則。
- 正式檢索階段不得讀取 `answer`、`gold`、`rationale` 或其他答案衍生欄位。

### 4.3 Fail closed

無法可靠連結時輸出 `unresolved`。不得為了提高覆蓋率而：

- 任選第一個候選。
- 任選 top-K 關係。
- 把空子圖改標成成功。
- 讓錯誤被後續模型常識作答掩蓋。

## 5. 356 題正規化資料契約

每題至少包含：

```json
{
  "qid": "IPAS-110-TEC-001",
  "source": "iPAS",
  "subject": "資訊安全技術",
  "year": 110,
  "stem": "題幹文字",
  "options": {
    "A": "選項 A",
    "B": "選項 B",
    "C": "選項 C",
    "D": "選項 D"
  },
  "answer": "A",
  "is_single": true,
  "split_meta": {
    "seed": 42,
    "ratio": 0.7,
    "strata_key": "原值"
  }
}
```

轉換規則：

1. `qid = record.qid`；若無則取 `record.id`。
2. `is_single = record.is_single`；若無則由 `qtype == "single"` 轉換。
3. `options` 必須剛好包含 A、B、C、D 且值非空。
4. `answer` 必須符合 `^[A-D]$`。
5. 356 個 `qid` 必須唯一。
6. ISN 應為 33 題，iPAS 應為 323 題。
7. 排除清單必須剛好 8 題，且與 356 題集合無交集。
8. 356 加 8 必須完整重建原 364 題集合。

## 6. 檢索輸入：完整題目但不洩漏答案

檢索端只允許讀：

- `stem`
- `options.A`
- `options.B`
- `options.C`
- `options.D`

每個 mention 必須保存來源：

```json
{
  "text": "SQL Injection",
  "normalized_text": "sql injection",
  "origin": "option_B",
  "source_span": "SQL Injection",
  "qid": "IPAS-..."
}
```

允許的 `origin` 固定為：

- `stem`
- `option_A`
- `option_B`
- `option_C`
- `option_D`

mention 必須能回指原始文字片段。不得由 Prompt 自行創造「系統」、「平台」、「技術」、「產出物」等原文不存在的抽象實體。概念同義展開只能在受控 alias 階段發生。

## 7. 最終作答仍是一次四選一

選項來源標記只服務於檢索與稽核，不改變作答格式。受測模型仍一次接收完整題目、全部選項與統一 evidence set，輸出：

```json
{
  "answer": "A",
  "reasoning": "作答理由"
}
```

禁止重啟兩條已證實失敗的路線：

- 每個選項各輸出一組 `is_correct` JSON。
- 把四個選項拆成四次獨立 True/False 判定。

## 8. Precision-first 實體連結

### 8.1 第一層：正規化後精確匹配

只對 `KGNode.name` 建立索引。正規化至少包括：

- Unicode NFKC。
- 英文 casefold。
- 頭尾空白移除與連續空白合併。
- 全形／半形與常見連字號統一。

現行 2,763 個 `KGNode.name` 無正規化重名；精確命中可直接接受。

### 8.2 第二層：經審核的 alias

alias 表必須版本化並可人工檢查。可包含：

- 中英文全名與縮寫，例如 `MFA`。
- 已確認的技術同義詞，例如 `SQLi`。
- 節點名稱括號內外的安全拆分。

不得把現行 `display_name` 全量視為 alias。已發現 `tcsec → ITSEC`、`攻擊 → 中間人攻擊`、`訊息摘要 → 數位簽章` 等不可逆或錯誤對應。

建議設定檔位置：

- `platform/backend/exp_3/config/entity_aliases.json`

### 8.3 第三層：語意候選與信心閘門

前兩層未命中時，使用固定且不隨受測模型改變的 embedding 模型對 `KGNode.name` 產生候選。候選階段只列出 top-k，不直接等於接受。

接受語意候選必須同時滿足：

1. 第一名相似度高於凍結門檻。
2. 第一名與第二名的差距高於凍結 margin。
3. 候選不是過短或泛化詞造成的大量碰撞。
4. 若相似候選無法唯一判斷，輸出 `unresolved`。

門檻與 margin 必須使用建構集校準，並在接觸正式留測執行前寫入版本化設定檔。建議設定檔位置：

- `platform/backend/exp_3/config/entity_linker_config.json`

校準目標為 precision-first：在建構集人工標註樣本上，優先滿足已接受連結 precision ≥ 95%，再於此限制下提高 recall。若無法達到 95%，不得以降低門檻換取表面覆蓋率，必須回到候選生成或 alias 品質處理。

## 9. 實體連結輸出與稽核契約

每個 mention 都要保留完整結果：

```json
{
  "qid": "IPAS-...",
  "mention": "SQL Injection",
  "origin": "option_B",
  "normalized_mention": "sql injection",
  "status": "exact",
  "matched_node": {
    "element_id": "4:...",
    "name": "sql injection",
    "type": "attack"
  },
  "candidates": [
    {
      "name": "sql injection",
      "score": 1.0,
      "rank": 1
    }
  ],
  "decision_reason": "normalized exact match"
}
```

`status` 固定為：

- `exact`
- `alias`
- `semantic`
- `unresolved`
- `rejected_generic`

不得只保留最後節點而丟棄候選與理由。

## 10. 必報指標

正式跑批前的建構集驗證至少要報：

- mention 總數。
- exact／alias／semantic／unresolved／rejected_generic 各自數量與比例。
- 已接受連結的人工驗證 precision。
- 無法連結的主要原因分布。
- 每題接受實體數分布。
- 0 實體題數。
- 候選歧義率。

正式 356 題只報凍結方法產生的結果，不使用答案回頭修連結。

## 11. 驗收條件

本文件所述部分要進入下一階段，至少必須滿足：

1. 356 題正規化檔通過第 5 節全部不變量。
2. 8 題排除 manifest 完整且可追溯至原 364 題。
3. 任一 mention 都能回指 stem 或某個 option 的原文字片段。
4. 程式中不存在原雙向 `CONTAINS + LIMIT 1` 自動接受路徑。
5. `display_name` 不會被無條件當成 alias。
6. 建構集校準設定與 alias 表均有版本化檔案。
7. 正式留測開始前產生設定檔雜湊；開始後不得改動。
8. 每一個 accepted／unresolved 決定均能由輸出 JSON 重建原因。

## 12. B4 開跑前仍需完成的設計與工程

以下項目不是本文件遺漏，而是後續必須獨立拍板的工作；在全部完成前，B4 維持禁止開跑：

1. **Mention extractor 實作選擇**：決定採固定共享 extractor 或保留每模型自行抽取；必須評估因果控制與成本。
2. **關係候選選擇**：取代「無相關就任選 top-K」；定義允許空集合、方向與關係排序。
3. **子圖展開策略**：明確定義實際 hop 數、正反向邊、每節點／每題上限與去重規則；修正現行 `MAX_HOP=3` 但只延伸一次的落差。
4. **Evidence 排序與預算**：定義全題 evidence 分數、來源平衡、衝突 evidence、最大三元組數與 token 上限。
5. **base／RAG Prompt 控制**：兩組須使用相同任務指令與相同 few-shot，只允許 evidence 區塊不同；確認空 evidence 題如何納入分析。
6. **完整 preflight 與掃錯閘門**：驗證 4 模型、356 題、2 arms、共 2,848 筆作答；NF1／檢索錯誤、缺題、空圖與缺 arm 都必須被偵測。
7. **測試策略**：先寫失敗測試，涵蓋 schema 正規化、8 題排除、精確／alias／語意／拒絕匹配、qid 集合一致與錯誤傳播。
8. **代表性 smoke set**：5 題樣本必須同時涵蓋 ISN 與 iPAS、精確命中／alias／語意／unresolved 情境；NF1 與兩個 arms 使用同一份樣本檔。
9. **離線驗證與設定凍結**：先在建構集完成，不得呼叫正式留測答案調參；產生設定雜湊與凍結紀錄。
10. **端點 smoke 與成本閘門**：上述全部 PASS 後，才執行四模型小樣本；回報成本與時間，經使用者同意後才能全量。
11. **文件同步**：把正式分母 356、新方法名稱、排除理由與結果檔路徑同步到 B4 交接、進度檢查點、Prompt 彙整與最後論文方法章。

## 13. 後續 Session 開場順序

接手者必須依序：

1. 讀本文件全文。
2. 讀 `論文\論文修訂\重跑交接B4_GraphRAG與對照表_20260705.md` 尾端最新追記。
3. 讀 `論文\論文修訂\重跑B進度檢查點.md` 的 B3 與 B4 前置拍板。
4. 確認沒有啟動任何 B4 模型跑批。
5. 從第 12 節第 1 項開始逐項設計、每項經使用者確認後再進下一項。
6. 全部設計核准後才建立 implementation plan；未核准前禁止改程式。

## 14. 已知權威數字

- 現行 Neo4j：2,763 個 `KGNode`、3,803 條 16 型別關係。
- 原 scoped 留測：364 題，全單選。
- 排除視覺依賴題：8 題。
- 新正式文字型留測：356 題＝ISN 33＋iPAS 323。
- 受測模型仍暫定：e4b、gptoss、gemma31b、llama70b；端點版本依 B4 交接最新追記。

---

本文件是 B4 正確性優先重設的第一份權威設計。若其他舊記憶、舊 Prompt 或舊程式與本文件在上述核准範圍內衝突，以本文件與 2026-07-12 使用者拍板為準。

---

## 追記（2026-07-12：route 2 — 移除人工步驟，改模型在環連結；已拍板並實作）

使用者拍板：實體連結**移除全部人工步驟**（人工 alias 建置、人工 gold 標記、threshold/margin 校準），改為全自動、模型自己決定，精神上與舊版一致（只比 base vs RAG 端到端結果）；但**不得回退到舊 `CONTAINS + LIMIT 1` 的任意任選**。本追記在下列範圍內**取代**前文對應段落：

1. **取代 §8.2（人工審核 alias）**：alias 層保留於程式中但預設為空、inert；不再要求人工建置或標記 `frozen`。
2. **取代 §8.3（語意門檻閘門）＋ §10「人工驗證 precision」＋ §11 第 5–6 條**：不再有 threshold/margin、gold labeling 或 precision≥95% 目標。改為 **route 2 模型在環連結**：
   - 第一層 normalized exact match（唯一命中）自動接受，免模型（保留 §8.1）。
   - exact 未命中或 exact 撞名 → 取固定 embedding（`text-embedding-embeddinggemma-300m-qat`）top-k 候選 → 交**同一受測模型**（per-model retrieval）在**受限候選集**內選一個 `element_id` 或 `null`。
   - Fail closed 不變：模型選 `null` 或選候選集以外的 id → `unresolved`；禁止任選節點（§4.3 精神保留）。
   - 每題所有待決 mention 併成**一次**模型呼叫（成本＝4 模型 × 356 題 ≈ 1,424 次連結呼叫，與 arm 無關）。
3. **§12 第 1、2 項調整**：mention extractor 仍每模型自抽；「關係候選選擇」不變（Step 2b 仍從候選集合選、空集合合法）。原「人工校準與設定凍結」改為：route 2 無門檻可調，freeze 只鎖 356 題＋smoke＋linker config＋prompts（含 `b4_node_linking.md`）的 sha256。
4. **必報指標（更新）**：exact 命中率、model_pick 比例、unresolved 比例、rejected_generic 比例、每題接受實體數分布、0 實體題數。不再報「人工驗證 precision」。
5. **口試守法**：實體連結亦交由受測模型在受限候選集內決定，無研究者手動標記或調參；無把握則不連，空子圖時 RAG 退回 base 知識作答——這是誠實的端到端結果。

**實作狀態（2026-07-12）**：已完成並通過驗證。`b4/entity_linker.py` 改為 `propose()`/`finalize_choice()` 兩段式＋`node_picker`（不重複 embedding）；新增 `b4/model_node_linking.py`＋`prompts/exp_3/b4_node_linking.md`；`exp_3_nf1_pipeline.py` 重構為三段式（propose → 每題批次模型選擇 → finalize）；`entity_linker_config.json`/`entity_aliases.json` 改 route 2；`calibration.py`＋兩支校準腳本退役、`test_b4_calibration.py` 刪除；`preflight_b4.py` freeze 拆除 threshold/alias-frozen 閘門。B4 全套單測 57 PASS、pipeline import／compile 乾淨、兩段式連結整合 smoke 通過（未呼叫外部 API）。

