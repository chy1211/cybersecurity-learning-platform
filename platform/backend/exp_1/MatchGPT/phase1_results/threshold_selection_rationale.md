# MatchGPT Threshold 選擇理由

## 選定值：threshold = 0.7

## 選擇邏輯
1. 硬性前提：跨類別合併率 = 0%（確保本體論一致性）
2. 次要目標：節點縮減比最大（結構改善幅度最大）

## 各 threshold 對比
| threshold | 節點縮減比 | 跨類別合併率 | WCC 數 | Leiden modularity |
|-----------|-----------|------------|--------|------------------|
| 0.7 | 0.1904 | 0.0000 | 153 | 0.7333 | ← 選定

## 備份位置
- 選定 threshold 備份：`phase1_backups/postmatchgpt_t07.json`
- Final 圖譜備份：`phase1_backups/final_kg.json`
- Neo4j 當前狀態：final 圖譜（Phase 2 直接接續）
