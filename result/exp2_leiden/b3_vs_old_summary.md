# B3 彙整：新圖 Leiden 三層驗證結果 vs 舊值對照（2026-07-12）

> 新圖＝全鏈唯一圖（2763 節點／3803 關係，B2 PASS 定版，平台格式轉換後）；舊值＝20260602A 定稿（舊圖 2832 節點）。
> 每個數字附來源檔；「舊掃描檔 174」屬舊圖 legacy 口徑，勿直接比對（重跑程式就緒清單 §2-5）。

## 一、選定參數與分群數三口徑

| 項目 | 新圖 | 舊值 | 新值來源 |
|------|------|------|----------|
| 選定參數 | **γ=1.5、minSize=3**（與舊相同） | γ=1.5、k=3 | `leiden_18params_compare.json`（status=finalized, selected） |
| raw 分群總數（GDS communityCount） | 192 | （舊掃描檔 174，legacy 口徑） | 同上 results |
| 有效分群數（規模≥3；＝communityId 寫回群數） | **87** | — | 同上＋DB distinct communityId=87（Codex 工單#2 步驟0） |
| 主要分群數（規模≥10） | **40** | 36（舊表12「有效分群數」即此口徑） | `scan_material_table.md` 表A |
| modularity | **0.719981** | 0.6663 | scan JSON γ1.5/m3 列 |
| Top-50 覆蓋率 | 95.07% | 97.4% | 同上 |
| 最大分群佔比／規模 | 5.83%／149 | 5.6%／— | 同上 |
| 入群節點覆蓋 | 2554/2763＝92.44% | — | finalize 輸出＋DB 實測 |
| 隨機種子 | 42（scan 與 finalize 同源屬性） | 42 | step2_1_leiden.py RANDOM_SEED |

⚠ 口徑提醒（銷 D3）：舊表12 的「有效分群數」＝規模≥10 口徑（36）；新報告採 B3 交接檔三口徑（raw／主要≥10／有效≥3），論文改寫時須明示口徑，新舊對照請用「主要分群數 40 vs 36」。

## 二、選組四準則證據（質性抽查摘要）

- γ=1.0 混併：最大群 210 節點將「風險管理/BCP」「法規個資」「ISMS 治理」併為一群（交叉表：γ1.5 下拆為 85/55/32/22）；另一群混病毒勒索＋備份稽核＋雜湊完整性。
- γ=1.5 主題清晰：弱點與測試（149）、Web 攻擊（121）、雲端服務（116）、實體安全（84）、密碼學（83）、風險與營運持續（85）各自成群。
- γ=2.0 強拆：γ1.5 之「弱點與測試」149 被拆 69/54/19；「雲端服務」116 被拆 67/49；且 γ2.0 仍有混雜群（行動通訊＋ISO 27001:2022）。
- 證據檔：`_tooling\b3_qualcheck.txt`（三組 top-8 群內容＋跨組成員交叉表，DB 暫存屬性抽查）。

## 三、Layer 1（演算法層）

來源：`layer1_metrics.json`（selected_config=γ1.5/m3）。18 組草稿表＋規模分布圖已產出（`layer1_metrics.md`／`layer1_size_distribution.png`）。
注意：layer1 的 size_distribution 欄位為桶中點近似展開（腳本既有行為），引用分布數字請以 scan JSON 的 sizeDistribution 五桶原值為準。

## 四、Layer 2（語意層）

**本體富集（method1；`layer2\layer2_method1_enrichment.json`）**

| 指標 | 新圖 | 舊值 |
|------|------|------|
| 低熵分群（entropy＜全圖背景） | **39/40** | 35/36 |
| 顯著富集分群（BH q<0.05） | **26/40**（34 個 community×type 對；q<0.10 為 31/40、42 對） | 17/36 |
| 背景 | 全圖 entropy 3.4785；40 主要分群、2375 節點、600 次比較 | — |

**embedding 語意對齊＋表16 雙檢定（method2；`layer2\layer2_method2_results.json`）**

| 指標 | 新圖 | 舊值 |
|------|------|------|
| 配對數 | 同群 800／跨群 800（min_size=10、pairs/community=20、seed=42） | 720/720 |
| 平均 cosine | 同群 0.5202／跨群 0.5042（差 0.0160） | — |
| Welch t | t=4.2312、p=2.4573e-05 | — |
| Mann-Whitney U（P13 銷案，雙檢定併列） | U=356071.0、p=9.4801e-05 | （舊僅 t 檢定） |
| Cohen's d | **0.2116** | 0.197 |
| 結論 | 兩檢定皆顯著；效果量小、「統計上一致的語意凝聚趨勢」敘事與舊圖一致 | 同 |

embedding 模型＝`text-embedding-embeddinggemma-300m-qat`（<local-openai-compatible-endpoint>）；新圖 1717 個節點名全新嵌入（舊快取檔不在預設路徑，從頭計算，快取落 `layer2\layer2_method2_embeddings_cache.json` 29MB）。

## 五、Layer 3（任務層章節覆蓋）

來源：`layer3_dominant.json`／`layer3_topn.json`；章節字典 `source_file_to_chapter.yaml`（20 章節單元、40 教材檔、SKIP=1 題庫、UNMATCHED=0）；CCOD `ccod_ranking.csv`（87 列，rank1=cid13 Web攻擊群，ccod=102）。

| 口徑 | mean 主導章節覆蓋 | median | ≥70% 群數 |
|------|------------------|--------|-----------|
| 全部 87 群（腳本原始輸出） | 31.51% | 18.45% | 16 |
| 主要分群（≥10，40 群） | 30.36% | 25.00% | 2 |
| **主要分群、以有章節歸屬節點為分母**（校正） | **48.99%** | 43.38% | 9 |
| 舊值（36 主要分群） | 50.5% | — | — |

**判讀（口試/論文揭露線）**：新圖 43.93%（1122/2554）入群節點僅有考題來源（`question_corpus_scoped.json`；章節覆蓋依設計 SKIP 題庫），原始口徑分母被結構性稀釋；排除無章節歸屬節點後，主要分群之主導章節覆蓋 48.99%≈舊值 50.5%，顯示**分群與教材章節之對應強度與舊圖相當**，原始值下降係語料重拍板（考題 854 題入建構語料）之預期構成效應，非分群品質退化。校正值計算：per-community dominant_count ÷ 該群有非題庫來源之節點數（scratchpad `b3_layer3_adjusted.py`，UNMATCHED=0 故非題庫來源必有章節）。
Top-N 覆蓋曲線（size_desc）：n1=6.8%、n3=17.2%、n5=25.6%、n10=40.5%（`layer3_topn.json`）。

## 六、平台格式轉換（B3 前置，記錄供 B4）

- 泛型定版圖→平台格式：`convert_generic_to_platform.py`（無損：加 :KGNode、RELATION→16 型別關係屬性原封、節點補 source_file 清單）；逐項對帳 final_kg.json PASS（16 型別分布全等、2763/3803、0 自環、孤兒 1）。
- 不採舊鏈 `apply_matchgpt_to_platform.py`（重灌＋重放會使節點數偏離 2763、口徑分叉）。
- 還原點：`phase1_backups\final_platform_kg.json`（修復版 backup/restore 工具）；現行庫另含 communityId／communityCCOD／communityFoundationRank（B3 產物屬性）。
