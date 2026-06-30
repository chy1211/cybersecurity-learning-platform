# 平台格式最終圖譜還原指南

> 建立日期：2026-05-20
> 對應論文：§參-五.2 MatchGPT 進階節點整併
> 目的：在 Neo4j 中建立可直接供平台使用的 final 知識圖譜

---

## 背景

本研究的知識圖譜建構分兩個層次：

| 層次 | 格式 | 用途 |
|---|---|---|
| **Phase 1 實驗格式** | 所有節點標 `:Entity`，關係統一 `:RELATION` | 供 MatchGPT / GDS 實驗用 |
| **平台格式** | 每類節點有自己的 label（`:policy`、`:feature`…），關係為語意名稱（`:mitigates`、`:uses`…） | 供平台後端（Flask API）直接查詢 |

`apply_matchgpt_to_platform.py` 負責將兩者橋接——用平台格式還原圖譜，再套用 MatchGPT 選定的合併結果。

---

## 關鍵檔案一覽

```
backend/exp_1/MatchGPT/
├── phase1_scripts/
│   └── apply_matchgpt_to_platform.py   ← 主腳本（本指南說明的）
├── phase1_results/
│   └── matchgpt_merged_t07.csv         ← MatchGPT t=0.7 合併清單（871 對）
├── phase1_backups/
│   └── final_platform_kg.json          ← 平台格式 final 圖譜備份
└── PLATFORM_KG_RESTORE_GUIDE.md        ← 本文件
```

---

## 完整還原步驟（從零開始）

### 前提條件
- Neo4j 已啟動（bolt://127.0.0.1:7687，neo4j/<NEO4J_PASSWORD>）
- APOC 套件已安裝
- `backend/ETL_module/Validated/` 資料夾存在（5,486 筆三元組）

### 方法 A：一行指令（推薦）

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\exp_1\MatchGPT'
python phase1_scripts\apply_matchgpt_to_platform.py
```

腳本會自動執行：
1. 清空 Neo4j
2. 從 `Validated/` 以平台格式匯入（~5 分鐘）
3. 套用 `matchgpt_merged_t07.csv` 的 871 對合併（~2 分鐘）
4. 備份至 `phase1_backups/final_platform_kg.json`

### 方法 B：只還原備份（不重跑匯入，速度快）

若 `final_platform_kg.json` 備份存在，可直接用 `neo4j_backup_restore.py` 還原：

```powershell
Set-Location -LiteralPath '.\CybersecurityLearningPlatform\backend\exp_1\MatchGPT'
python neo4j_backup_restore.py restore phase1_backups\final_platform_kg.json --yes
```

> ⚠️ 注意：此備份工具對「同一對節點的多條不同語意關係邊」有約 0.8% 損失（known artifact）。
> 若需完全精確，請用方法 A。

---

## 平台格式說明

還原後的 Neo4j 圖譜格式如下：

### 節點
```cypher
// 範例：policy 類型節點
(:policy {
  name: "iso/iec 27001",          // 正規化小寫名稱（MERGE key）
  display_name: "ISO/IEC 27001",  // 顯示用原始大小寫
  source_file: ["第01章...pdf", "第05章...pdf"],  // 出現過的 PDF（陣列）
  source_id: ["chunk_1", "chunk_3"],              // 所在 chunk（陣列）
  source_index: [1, 7]                            // chunk 內索引（陣列）
})
```

**15 種節點類型**（label）：
`feature`, `function`, `attack`, `vulnerability`, `technique`, `data`,
`principle`, `risk`, `tool`, `system`, `app`, `policy`, `attacker`,
`securityTeam`, `user`

### 關係
```cypher
// 範例：mitigates 關係
(:policy {name: "iso/iec 27001"})-[:mitigates {
  source_file: ["第01章...pdf"],
  source_id: ["chunk_1"],
  source_index: [1]
}]->(:attack {name: "資訊安全威脅"})
```

**16 種關係類型**：
`has_a`, `can_analyze`, `can_expose`, `can_exploit`, `implements`,
`uses`, `can_harm`, `can_detect`, `is_part_of`, `mitigates`, `violates`,
`deployed_in`, `generates`, `connects_to`, `depends_on`, `controls`

---

## MatchGPT 合併邏輯說明

`matchgpt_merged_t07.csv` 記錄了 871 對 LLM 判定為同義詞的節點對。

合併策略（`apply_matchgpt_to_platform.py` 第 80-110 行）：
1. **保留節點 A**（name_a）：name、display_name、label 全部不變
2. **合併來源資訊**：將 B 的 source_file/source_id/source_index 陣列追加到 A
3. **重新導向關係**：B 的所有入/出邊全部移到 A（APOC mergeNodes）
4. **刪除節點 B**

---

## 數字摘要（2026-05-20 執行結果）

| 階段 | 節點數 | 關係數 | 說明 |
|---|---|---|---|
| 還原後（合併前）| 3,733 | 4,842 | 5,486 筆三元組匯入，648 個 chunk 檔 |
| 套用 MatchGPT 後 | **2,862** | **4,506** | 節點縮減 871（23.3%） |
| final_platform_kg.json | 2,862 | 4,506 | 4.09 MB |

**合併統計**：
- 成功合併：871 對
- 節點已消失（先前被合併，cascade 效果）：837 對
- 跨類別跳過：0 對（本體論一致性完全保持）
- 錯誤：0 對

**合併後 Label 分布（前 5）**：`:tool` 441、`:technique` 368、`:system` 359、`:feature` 350、`:data` 261

**合併後關係 type 分布（前 5）**：`:hasa` 979、`:mitigates` 611、`:ispartof` 457、`:uses` 455、`:cananalyze` 423

詳細數字見 `phase1_results/platform_merge_stats.json`。

---

## 依賴關係圖

```
ETL_module/Validated/          ← 5,486 筆三元組（四步驟驗證後）
         ↓
03b_restore_neo4j.py（邏輯）   ← 平台格式匯入
         ↓
Neo4j（平台格式，未合併）
         ↓
phase1_results/matchgpt_merged_t07.csv   ← MatchGPT t=0.7 判定結果
         ↓
apply_matchgpt_to_platform.py  ← 本腳本
         ↓
Neo4j（平台格式，已合併）= final_platform_kg.json
         ↓
平台後端 Flask API 直接使用
```


