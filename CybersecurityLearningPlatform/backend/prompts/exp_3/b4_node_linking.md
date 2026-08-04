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
