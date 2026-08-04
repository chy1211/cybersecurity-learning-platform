# Layer 2 Method 1：本體屬性富集分析摘要

**生成時間**：2026-07-11T23:32:00

## 分析範圍
- 社群最小節點數門檻：10（依據 Halu et al., 2019）
- 有效社群數：40
- Entity type 種類：15
- 多重比較次數：600
- 母體節點數 (M)：2375

## Shannon Entropy（描述統計）
- 全圖背景 entropy：**3.4785**
- 社群 entropy 平均：**2.8529**
- 社群 entropy 中位：**2.9676**
- entropy 低於全圖背景的社群：39 / 40

## Hypergeometric Enrichment + BH 校正（正式推論）
- 顯著 (community, type) 對（q < 0.05）：**34**
- 涉及社群數（q < 0.05）：**26 / 40**
- 補充分析（q < 0.10）：42 對，涉及 31 個社群

## 論文引用語（草稿）

在 40 個有效社群（≥10 節點）中，共有 26 個社群呈現至少一種 entity type 的顯著富集（Hypergeometric test，BH-adjusted q < 0.05），佐證 Leiden 拓樸分群具有非隨機的本體論型別收斂性（Singh et al., 2023）。