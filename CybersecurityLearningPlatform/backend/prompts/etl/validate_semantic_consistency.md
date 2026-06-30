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
{{
"step_1_rule_matching": "針對每條相關規則，說明三元組是否觸發違規。",
"response": "correct 或 violation",
"reason": "最終判定理由（不超過兩句話）。"
}}
