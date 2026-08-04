# 06 實驗三：B4 逐模型子圖檢索（route 2）

- **論文章節**：§參-八 評估實驗三之子圖檢索階段
- **正式流程**：每個受測模型各自執行 Step 1 題幹／選項主張分解、受限候選集實體連結、Step 2 關係選擇與二跳子圖擷取；不得共用其他模型的 mention 或 subgraph。
- **模型**：`gemma-4-e4b-it`、`openai/gpt-oss-20b`、`meta/llama-3.1-70b-instruct`、`google/gemma-4-31b-it`，皆由同一受測模型完成該模型自己的檢索判斷。
- **權威執行來源**：
  - `論文\交接\platform\backend\exp_3\exp_3_nf1_pipeline.py`
  - `backend\prompts\exp_3\nf1_step1_system.md`
  - `backend\prompts\exp_3\nf1_step1_sentence_divide_json_zh.txt`
  - `backend\prompts\exp_3\b4_node_linking.md`
  - `backend\prompts\exp_3\nf1_step2_system.md`
  - `backend\prompts\exp_3\nf1_step2_relation_retrieval_json_zh.txt`

> 以下為最後一次正式 B4 route-2 實驗實際載入的三組模型 Prompt。正式 Step 1 使用包含題幹與 A–D 選項、但不含正解與 rationale 的 `<<<<QUESTION_JSON>>>>`。

## Step 1：題目主張與 mention 分解

### System Prompt

```text
你是資安領域之專家助理。請依範例之 JSON 格式分解資安主張為單一三元組之子句。
```

### User Prompt 模板

```text
請閱讀完整題目，包括題幹與 A、B、C、D 四個選項，將其中需要查詢知識圖譜的主張整理成子主張。

你只能抽取題目原文中實際出現的 mention，不得自行創造「系統」、「平台」、「技術」、「產出物」或其他原文不存在的抽象實體。

每個 mention 必須包含：
- text：mention 文字。
- origin：只能是 stem、option_A、option_B、option_C、option_D。
- source_span：該 mention 在原始題幹或選項中實際出現的連續文字片段。

規則：
1. source_span 必須逐字出現在指定 origin 的原文中。
2. 不要把答案、gold、rationale 或任何答案衍生資訊加入輸出。
3. 同一個 mention 若出現在不同來源，分別保留來源。
4. 如果沒有可靠的原文 mention，mentions 可以是空陣列。
5. 最終的四選一作答不是本步驟的工作。

必須以 JSON 格式回答：
{"sub_claims": [{"subclaim_id": "0", "text": "原文子主張", "mentions": [{"text": "SQL Injection", "origin": "stem", "source_span": "SQL Injection"}]}]}

題目：<<<<QUESTION_JSON>>>>
```

`<<<<QUESTION_JSON>>>>` 由 `{"stem": 題幹, "options": {"A": ..., "B": ..., "C": ..., "D": ...}}` 緊縮 JSON 取代；不含正確答案與 rationale。

## Route 2：受測模型在環實體連結

### System Prompt

```text
你是嚴謹的資安知識圖譜實體連結器，只輸出符合 schema 的 JSON。
```

### User Prompt 模板

```text
你是資安知識圖譜的實體連結器。下面每個 mention 是從一道資安考題的題幹或選項擷取出的字串,附上知識圖譜中最相近的候選節點。請為每個 mention 判斷它**指涉**的是哪一個候選節點。

規則:
1. 只能從該 mention **自己的 candidates 清單**裡選一個 `element_id`;不得輸出清單以外的 id。
2. 若沒有任何候選節點能明確對應該 mention(語意不符、只是泛稱、無把握),`element_id` 一律填 `null`。**寧可 null,不要勉強配對。**
3. 逐一處理,不要漏掉任何 index。

輸入(mentions 與各自候選):
<<<<MENTIONS_JSON>>>>

只輸出符合下列 schema 的 JSON,不要多餘文字:
{
  "choices": [
    {"index": 0, "element_id": "<候選之一的 element_id 或 null>"},
    {"index": 1, "element_id": null}
  ]
}
```

`<<<<MENTIONS_JSON>>>>` 由待判定 mention 與其固定候選節點清單組成；模型只能選候選中的 `element_id` 或 `null`，清單外輸出一律 fail closed。

## Step 2：候選關係選擇

### System Prompt

```text
你是資安領域之專家助理。請從關係集合中選出與子句最相關之 top-K 個關係，並以 JSON 回答。
```

### User Prompt 模板

```text
請從給定的候選關係集合中，選出與子主張直接相關的關係。

規則：
1. 只能選擇關係集合中已存在的關係，不得創造新關係。
2. 最多選 <<<<TOP_K>>>> 個關係。
3. 如果沒有足夠相關的關係，selected_relations 必須回傳空陣列。
4. 不得因為需要填滿數量而任選關係。
5. decision_reason 必須簡短說明選擇或回傳空集合的原因。

請以 JSON 格式回答：
{"selected_relations": ["關係1", "關係2"], "decision_reason": "選擇理由"}

子主張：<<<<SENTENCE>>>>
候選關係集合：<<<<RELATION_SET>>>>
```

- `<<<<TOP_K>>>>`：正式值 10。
- `<<<<SENTENCE>>>>`：Step 1 產生的單一子主張。
- `<<<<RELATION_SET>>>>`：由已連結節點鄰接關係形成的候選集合。
- 選定關係後以 `MAX_HOP=2` 擷取並排序證據，形成 05 作答 Prompt 的 `evidence_block`。
