# result/ — 實驗結果

本目錄集中存放三個評估實驗**最後一次執行（2026-07 全鏈重跑）**的結果。
圖譜狀態為 **2,763 節點／3,803 關係／87 分群**。

各實驗腳本的預設輸出路徑已指向此處，重跑後產物會直接落在對應子目錄。

```
result/
  exp2_leiden/      實驗二：Leiden 分群有效性（含群內中心性與拓樸分層）
  exp3_graphrag/    實驗三：Graph RAG 事實正確性
```

> 實驗一（圖譜品質驗證與 MatchGPT）的指標仍位於
> `platform/backend/exp_1/MatchGPT/phase1_results/`，
> 尚未搬遷，以免影響該階段腳本既有的讀寫路徑。

---

## exp2_leiden/

| 檔案 | 內容 | 產生者 |
|---|---|---|
| `leiden_18params_compare.json` | 18 組 γ×minSize 參數掃描（seed=42）與 finalize 狀態 | `exp_2/phase2/step2_1_leiden.py` |
| `scan_material_table.md` | 參數掃描素材表 | 同上 |
| `layer1_metrics.json`／`layer1_size_distribution.png` | 第一層：演算法指標與分群規模分布 | `exp_2/exp_2_layer1_*.py` |
| `layer2/layer2_method1_enrichment.*` | 第二層方法一：本體富集（entropy + hypergeometric + BH） | `exp_2/exp_2_layer2_method1.py` |
| `layer2/layer2_method2_results.json`／`layer2_pairs.csv` | 第二層方法二：語意對齊與表16 雙檢定（Welch t／Mann-Whitney U） | `exp_2/exp_2_layer2_method2.py` |
| `layer3_dominant.json`／`layer3_topn.*` | 第三層：章節覆蓋與 CCOD 排序 | `exp_2/exp_2_layer3_*.py` |
| `ccod_ranking.csv`／`source_file_to_chapter.yaml`／`chapter_node_count.csv` | CCOD 排名與章節對應字典 | 同上 |
| `centrality_top3_by_community.csv` | 各分群內 degree／betweenness／closeness 前三名（min_size=10，40 個主要分群） | `exp_2/phase2/step2_3_centrality.py` |
| `Topological_Stratification_Centrality.md`／`_DirectedEdges.md` | 拓樸分層雙方法比較（出度分層 vs DAG） | `exp_2/phase2/step2_4_topo_layer.py` |
| `cycle_edges_removed.csv` | DAG 方法移除的循環邊紀錄 | 同上 |

**未納入版控**：`layer2_method2_embeddings_cache.json`（約 27.9 MB）。
它是 embeddinggemma-300m-qat 的節點名稱向量快取，可由 `exp_2_layer2_method2.py` 重新產生。

---

## exp3_graphrag/

| 檔案 | 內容 | 產生者 |
|---|---|---|
| `answer_formal/eval_{model}.json` | 四模型 × base／rag × 356 題的作答紀錄（答案、是否正確、gold、耗時） | `exp_3/exp_3_eval_batch.py` |
| `extract_formal/subgraph_nf1_{model}.json` | 四模型的子圖檢索結果（子claim、mention、實體連結、關係選擇、證據排序、保留邊數） | `exp_3/exp_3_nf1_pipeline.py` |
| `freeze_manifest.json` | 輸入凍結清單與雜湊，用於確認跑批輸入未變動 | `exp_3/scripts/preflight_b4.py --mode freeze` |
| `preflight_results_report.json` | 結果驗證報告（expected_records = 2848 = 4×356×2） | `exp_3/scripts/preflight_b4.py --mode results` |
| `flip_matrix_report.md`／`flip_analysis_summary.md`／`positive_flips_report.md` | base→rag 翻轉分析 | `exp_3/scripts/flip_matrix.py` |
| `affected_qids_footer.json` | 受考卷頁尾污染影響、已清理並重跑的 63 題清單 | 資料修復階段產生 |
| `heldout_question_index.json` | 留測集索引：僅題號與統計 | 見下方說明 |

### 關於題目資料

**本 repo 不散布考題內容。** 留測集（356 題，來源 iPAS／ITE）與建構集（854 題）的
題幹、選項與答案均不納入版控。`heldout_question_index.json` 只提供題號清單、
來源與年份統計，以及原始題庫檔的 SHA-256，讓他人能核對範圍與完整性而無需取得題目本身。

同樣地，`extract_formal/` 內每個子claim 的原文（`sub_claims[].text`）已置為 `null`，
改附 `text_sha256`。檢索結構、實體連結與證據三元組完整保留，
可據以驗證檢索行為；持有原始題庫者可用雜湊值逐筆對回。

### 未納入版控

- `extract_construction/`（建構集子圖檢索結果，約 115 MB）：屬中間產物，
  可由 `exp_3/scripts/run_b4_extraction_matrix.py` 以建構集重新產生。
- 各次跑批的 `*.log`：可能含 Prompt 與模型輸出片段。
