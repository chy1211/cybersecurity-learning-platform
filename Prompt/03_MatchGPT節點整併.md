# 03 MatchGPT 節點整併

- **論文章節**：§參-五.2 MatchGPT 節點整併模組（四階段驗證之後置全圖整併）
- **用途**：對通過四階段驗證並寫入之全圖節點，於本體論類別約束下判定同類別之兩節點是否指稱同一概念，以整併語意重複之同義節點。
- **模型**：`meta/llama-3.3-70b-instruct`（NVIDIA，多 key 並行）
- **參數**：`temperature=0.0`、`max_tokens=256`、`response_format={"type":"json_object"}`
- **候選篩選（blocking）**：第一層依本體論 15 類實體分桶（同類別才比對）；第二層於同類別內以 `text-embedding-embeddinggemma-300m-qat` 餘弦相似度做 top-k 篩選（`EMBED_SIM_THRESHOLD=0.80`、`TOP_K=10`）。
- **整併門檻**：掃描 confidence 門檻 {0.5, 0.7, 0.9}，最終以 **t=0.7** 定案。
- **輸出格式**：JSON，含 `decision`（`same` / `different`）、`confidence`（0.0–1.0）、`reason`。
- **來源檔案**：
  - `論文\CybersecurityLearningPlatform\backend\exp_1\MatchGPT\phase1_scripts\run_matchgpt.py`
    - 使用者提示詞：`build_matchgpt_prompt()`（第 173–188 行）
    - 系統提示詞：`call_llama_once()` 的 messages（第 199 行）
    - 模型／參數常數：`LLAMA_MODEL`（第 68 行）、`EMBED_MODEL`（第 80 行）、`EMBED_SIM_THRESHOLD`／`TOP_K`／`THRESHOLDS`（第 91–93 行）

---

## 系統提示詞

```text
你是資安知識圖譜整併專家，請嚴格依規則判斷，僅輸出 JSON。
```

## 使用者提示詞（`build_matchgpt_prompt`）

```text
你是知識圖譜整併專家。請判斷以下兩個知識圖譜節點是否指稱同一個概念。

本體論類別（兩節點均屬此類）：{type_a}（{type_def}）

節點 A：{name_a}
節點 B：{name_b}

判斷規則：
1. 若兩節點名稱語意等價、為同義詞、或一個是另一個的標準化形式，判定為 same
2. 若兩節點雖相關但指稱不同概念，判定為 different
3. confidence 反映你的確信程度（0.0 ~ 1.0）

請輸出 JSON（僅此 JSON，無其他文字）：
{"decision": "same" 或 "different", "confidence": 0.0~1.0的數字, "reason": "一句說明"}
```

---

## 變數說明

- `{type_a}`：兩節點所屬之本體論實體類別（兩節點同類別才會被送入判定）。
- `{type_def}`：該類別之中文定義（取自 `ENTITY_TYPE_DEFS` 對照表，如 `attacker → 攻擊者或威脅行為者`）。
- `{name_a}`／`{name_b}`：待比對之兩節點名稱。

## 設計對應（論文敘述）

- 將 Peeters & Bizer (2023) 為 MatchGPT 設計之 prompt 策略移植至圖譜場景，並於提示層級注入本體論類別約束（同類別才允許整併，例如不允許 Malware 與 Attacker 合併）。
- 對應「零樣本注入領域規則」設定：以類別語意說明引導 LLM 遵守本體論類別邊界，於低 API 成本下取得接近少樣本之配對效果。
- 評估採兩層量化指標：結構性指標（弱連通元件數、平均節點度、節點縮減比）與本體論一致性指標（跨類別合併率、關係保留率），而非人工標註精確率／召回率。
