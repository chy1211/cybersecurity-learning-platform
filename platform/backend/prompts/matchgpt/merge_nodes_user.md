你是知識圖譜整併專家。請判斷以下兩個知識圖譜節點是否指稱同一個概念。

本體論類別（兩節點均屬此類）：{type_a}（{type_def}）

節點 A：{name_a}
節點 B：{name_b}

判斷規則：
1. 若兩節點名稱語意等價、為同義詞、或一個是另一個的標準化形式，判定為 same
2. 若兩節點雖相關但指稱不同概念，判定為 different
3. confidence 反映你的確信程度（0.0 ~ 1.0）

請輸出 JSON（僅此 JSON，無其他文字）：
{{"decision": "same" 或 "different", "confidence": 0.0~1.0的數字, "reason": "一句說明"}}
