# B4 correctness-first retrieval runbook（route 2：模型在環連結）

本流程對應 `docs/superpowers/specs/2026-07-12-b4-correctness-first-retrieval-design.md` 及其 2026-07-12 route-2 追記。四個受測模型各自執行 Step 1、node linking、Step 2b 與檢索；不能把其中一個模型的 mention 或 subgraph 共用給其他模型。

## route 2 與原設計的差異（先讀）

2026-07-12 使用者拍板：**移除人工 alias 建置與人工門檻校準**，改為全自動、模型在環的實體連結,只比 base vs RAG 端到端結果。與原 spec §8.2/§8.3 相比：

- **保留** 第一層 normalized exact match（唯一命中自動接受，免模型）。
- **移除** 人工審核 alias 表（alias 層保留但預設空、inert）與 §8.3 的 threshold/margin 人工校準、gold labeling、precision≥95% 目標。
- **新增** node linking：exact 未命中或 exact 撞名時，取固定 embedding top-k 候選，交**同一受測模型**選一個 element_id 或 null；選清單外 id 或 null 一律 `unresolved`（fail closed）。每題所有待決 mention 併成**一次**模型呼叫。

## 目前已落地的規則

- 題目先經固定 normalization：正式留測 356 題，排除 8 題視覺題；construction 854 題另存，兩者來源檔不修改。
- Step 1 輸入包含 stem 與 A-D，但輸出只能引用原文 mention，且每筆保存 `origin` 與 `source_span`。
- Entity linking：normalized exact（唯一）→ inert alias → 模型在環候選選擇。無把握 `unresolved`，禁止任選節點。
- Step 2b 每個有候選關係的 subclaim 都呼叫對應受測模型；只能從候選集合選擇，空集合合法，解析/API 錯誤不得 fallback。
- 子圖固定雙向、最多 2-hop、每節點最多 50 triples、每題最多 100 candidates；最後 deterministic ranking 為每 origin 10、每題 30。
- Base 與 RAG 使用同一 system/task/few-shot；唯一差異是 evidence block。空證據明確輸出 `Evidence set: []`。
- 正式留測必須通過 freeze hash、smoke gate，並在 eval 時明確加 `--confirm-full-run`。

## 建構集與 smoke set

```text
python exp_3/scripts/prepare_b4_inputs.py --heldout ... --construction ... --output-dir ...
python -m exp_3.scripts.build_b4_smoke_set --construction ... --output-questions ... --output-manifest ...
```

固定 smoke qids 與 hash 會寫入 `b4_smoke_cases.json` 產生的 manifest；coverage target 是 exact、model_pick（semantic 與 exact-collision）、unresolved、multi-source/mentions。target 是驗證標籤，不能在 extractor 跑完前當成實測結果。

## 建議執行順序

1. 先以 construction 854 題執行 `run_b4_extraction_matrix.py`，輸出四份獨立 extractor audit（含每題 node-linking 決策、exact/model_pick/unresolved/rejected_generic 分布）。這步已呼叫 embedding endpoint 與受測模型 → 先估成本、經同意再全量。
2. 檢視 audit 的連結指標（§必報指標）：exact 命中率、model_pick 比例、unresolved 比例、每題接受實體數、0 實體題數。若品質不佳，先改善 embedding 候選或 Step 1 mention 品質，**不回頭調任何門檻**（route 2 已無門檻可調）。
3. `semantic` embedding model 固定為 `text-embedding-embeddinggemma-300m-qat`，快取獨立於舊 `embedding_cache.json`（存 `exp_3/cache/b4_semantic_index.json`）。
4. 用 `preflight_b4.py --mode freeze` 鎖定正式 356 題、smoke artifact、linker config 與 prompts（含 `b4_node_linking.md`）的 hash。alias 檔為可選 artifact。
5. 先執行 `run_b4_smoke.py --phase all`。retrieval artifact 或四模型 live answer 任一失敗，都停止正式 run。
6. 正式 extractor matrix 與 answer eval 完成後，用 `preflight_b4.py --mode results` 驗證恰好 `4 × 356 × 2 = 2848` 筆；API、parse、retrieval error 或空答案均 fail，空 evidence 不算錯誤。

## 已退役

- `calibrate_b4_linker.py`、`make_b4_calibration_template.py`：已改為 retired wrapper（route 2 無門檻校準／無人工標記）。
- `b4/calibration.py` 與 `tests/test_b4_calibration.py`：已刪除。

## 尚未執行的外部步驟

本次實作沒有呼叫 Neo4j、embedding endpoint 或四個 LLM API，也沒有產生正式 extractor/eval 結果。這些是需要在 config freeze 與 smoke PASS 後才允許執行的外部實驗步驟。
