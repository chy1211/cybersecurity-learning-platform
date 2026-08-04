# data/kg_snapshot/ — 權威圖譜快照

`platform_kg.json` 是可直接還原的知識圖譜快照，對應 2026-07 全鏈重跑的定版狀態。
沒有這份檔案，clone 下來的 repo 只有程式碼而沒有圖，平台與實驗二都跑不起來。

| 項目 | 值 |
|---|---|
| 節點 | 2,763 |
| 關係 | 3,803（16 種語意型別，0 自環） |
| 分群 | 87（`communityId` 覆蓋 2,554 個節點） |
| 格式 | 平台格式（節點帶 `:KGNode` 標籤，型別存於 `n.type` 屬性） |
| 來源 | 重跑鏈 B3 finalize 後的狀態，含 `communityId`／`communityCCOD`／`communityFoundationRank` |
| 大小 | 約 2.7 MB |
| SHA-256 | 見 `platform_kg.json.sha256` |

## 還原

```powershell
Set-Location -LiteralPath '.\platform\backend\exp_1\MatchGPT'
python neo4j_backup_restore.py restore ..\..\..\..\data\kg_snapshot\platform_kg.json --wipe
```

**必須加 `--wipe`**：只有 wipe 模式逐條 `CREATE` 重建關係、精確保留平行邊；
非 wipe 模式走 `MERGE`，同起訖同型別的平行邊會被塌縮成一條。

## 兩件要知道的事

1. **節點型別在 `n.type` 屬性，不在標籤上。**
   標籤只有 `:Entity` 與 `:KGNode`；15 種型別（feature／tool／technique／system…）
   存在 `n.type`。任何按標籤取型別的查詢對這版圖都會失準。
2. **群內中心性與分層屬性不在這份快照裡。**
   `outDegree_inCommunity`／`betweenness_inCommunity`／`nodeLayerInCommunity`
   由 `exp_2/phase2/step2_3_centrality.py` 與 `step2_4_topo_layer.py` 產生；
   平台的「結構導覽」頁需要它們，還原快照後請補跑這兩支（需要 GDS）。

## 去敏說明

原始備份檔的 `meta.neo4j_uri` 記錄了產生當下的內部主機位址，公開版本已移除該欄位。
節點與關係內容未做任何更動，`sha256` 對應的是此公開版本。
