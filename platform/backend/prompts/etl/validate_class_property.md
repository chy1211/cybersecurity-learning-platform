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
{{
"step_1_list_check": "說明主體類別、受體類別與關係是否皆在 Lc,p 中。",
"step_2_alignment_check": "判斷各實體名稱是否為其類別的合理實例（含同義詞寬容）。",
"response": "correct 或 violation",
"reason": "綜合上述步驟的一句話結論。"
}}
