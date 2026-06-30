#!/usr/bin/env python3
"""
從 matchgpt_decisions.csv 補生成三組 threshold 的合併明細 CSV。
在 run_matchgpt.py 完成後執行一次即可。
"""
import csv
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "phase1_results"
THRESHOLDS  = [0.5, 0.7, 0.9]

dec_path = RESULTS_DIR / "matchgpt_decisions.csv"
if not dec_path.exists():
    print(f"[ERROR] 找不到 {dec_path}")
    exit(1)

with open(dec_path, encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

print(f"載入判定結果：{len(rows)} 筆")

for t in THRESHOLDS:
    tstr = str(t).replace(".", "")
    out  = RESULTS_DIR / f"matchgpt_merged_t{tstr}.csv"
    if out.exists():
        print(f"[SKIP] {out.name} 已存在")
        continue
    pairs = [r for r in rows
             if r["decision"] == "same" and float(r["confidence"]) >= t]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name_a", "type_a", "name_b", "type_b",
                         "similarity", "confidence", "reason"])
        for p in pairs:
            writer.writerow([p["name_a"], p["type_a"], p["name_b"], p["type_b"],
                             p["similarity"], p["confidence"], p["reason"]])
    print(f"  t={t}：{len(pairs)} 對 → {out.name}")

print("✅ 完成")
