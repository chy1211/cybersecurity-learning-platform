#!/usr/bin/env python3
"""
三支分析腳本的 mock 驗證

建立 mock 輸入資料（貼近 Phase 1 實際 JSON 格式），
依序執行三支腳本，驗證輸出 JSON / Markdown 格式正確性。

執行：
  cd 論文/CybersecurityLearningPlatform/backend/ETL_module/exp_1
  python run_mock_tests.py
"""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PYTHON       = sys.executable

PASS_COUNT = 0
FAIL_COUNT = 0


def check(cond: bool, msg: str):
    global PASS_COUNT, FAIL_COUNT
    if cond:
        print(f"  ✓ {msg}")
        PASS_COUNT += 1
    else:
        print(f"  ✗ FAIL: {msg}")
        FAIL_COUNT += 1


# ─── Mock 資料（貼近 Phase 1 實際格式）─────────────────────────────────────────

MOCK_PRE_STATS = {
    "node_count": 4108,
    "relation_count":  5001,
    "isolated_node_count": 0,
    "avg_degree": 2.4348,
    "isolated_node_ratio": 0.0,
    "entity_type_distribution": {"tool": 562, "system": 529},
    "wcc_count": 347,
    "leiden_modularity_gamma1": 0.807377,
    "source": "pre_validation",
    "total_input_triples": 5593,
    "merged_triples": 5593,
    "timestamp": "2026-05-19T20:50:17.407017"
}

MOCK_POST_STATS = {
    "node_count": 3703,
    "relation_count":  4837,
    "isolated_node_count": 0,
    "avg_degree": 2.6125,
    "isolated_node_ratio": 0.0,
    "entity_type_distribution": {"tool": 531, "system": 504},
    "wcc_count": 248,
    "leiden_modularity_gamma1": 0.776492,
    "source": "post_validation",
    "total_input_triples": 5486,
    "merged_triples": 5486,
    "timestamp": "2026-05-19T20:58:17.840671"
}

MOCK_MATCHGPT_T07 = {
    "threshold": 0.7,
    "timestamp": "2026-05-19T22:30:00",
    "pre_merge": {"node_count": 3703, "rel_count": 4798},
    "post_merge": {
        "node_count": 3655,
        "relation_count":  4760,
        "isolated_node_count": 0,
        "isolated_node_ratio": 0.0,
        "avg_degree": 2.6042,
        "wcc_count":  238,
        "leiden_modularity_gamma1": 0.781234,
    },
    "merge_stats": {
        "merged_pairs": 46,
        "skipped_pairs": 2,
        "cross_type_blocked": 0,
        "cross_type_merge_rate": 0.0,
        "self_loops_after": 3,
        "post_rel_count": 4763,
        "relation_preservation_rate": 0.9927,
        "pairs_filtered": 48,
        "node_reduction": 48,
        "node_reduction_ratio": 0.0130,
    }
}

MOCK_SUMMARY = {
    "timestamp": "2026-05-19T22:45:00",
    "thresholds": [0.5, 0.7, 0.9],
    "structural": [
        {
            "threshold":            0.5,
            "node_count":           3620,
            "relation_count":       4690,
            "wcc_count":            225,
            "avg_degree":           2.592,
            "leiden_modularity":    0.783,
            "node_reduction_ratio": 0.0224,
        },
        {
            "threshold":            0.7,
            "node_count":           3655,
            "relation_count":       4760,
            "wcc_count":            238,
            "avg_degree":           2.604,
            "leiden_modularity":    0.781,
            "node_reduction_ratio": 0.0130,
        },
        {
            "threshold":            0.9,
            "node_count":           3690,
            "relation_count":       4815,
            "wcc_count":            244,
            "avg_degree":           2.611,
            "leiden_modularity":    0.778,
            "node_reduction_ratio": 0.0035,
        },
    ],
    "ontology_consistency": [
        {
            "threshold":                  0.5,
            "pairs_filtered":             120,
            "merged_pairs":               83,
            "cross_category_merge_rate":  0.0,
            "relation_preservation_rate": 0.9694,
        },
        {
            "threshold":                  0.7,
            "pairs_filtered":             48,
            "merged_pairs":               46,
            "cross_category_merge_rate":  0.0,
            "relation_preservation_rate": 0.9927,
        },
        {
            "threshold":                  0.9,
            "pairs_filtered":             13,
            "merged_pairs":               13,
            "cross_category_merge_rate":  0.0,
            "relation_preservation_rate": 0.9986,
        },
    ],
}

MOCK_DECISIONS_ROWS = [
    ("交易的安全性", "feature", "交易安全",     "feature", 0.9669, "same",      0.95, "語意等價"),
    ("外圍層",       "feature", "外部層",        "feature", 0.9498, "same",      0.82, "同義詞"),
    ("udp/tcp 協定", "feature", "udp 協定",      "feature", 0.9347, "different", 0.90, "範疇不同"),
    ("漏洞掃描",     "tool",    "漏洞掃描工具",  "tool",    0.9200, "same",      0.88, "縮寫等價"),
    ("社會工程",     "attack",  "釣魚攻擊",      "attack",  0.8800, "different", 0.75, "子類非同義"),
]


# ─── Mock 測試執行 ──────────────────────────────────────────────────────────────

def run_test(label: str, cmd: list[str], work_dir: Path) -> tuple[bool, str]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(work_dir),
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    ok = result.returncode == 0
    output = stdout if stdout else stderr
    return ok, output


def test_indicator3(tmp: Path):
    print("\n[Test 1] exp_1_indicator3_prepost.py")

    # 寫 mock 輸入
    pre_path  = tmp / "pre_validation_stats.json"
    post_path = tmp / "post_validation_stats.json"
    mgpt_path = tmp / "matchgpt_t07_metrics.json"
    out_path  = tmp / "indicator3_prepost_compare.json"

    pre_path.write_text(json.dumps(MOCK_PRE_STATS,   ensure_ascii=False), encoding="utf-8")
    post_path.write_text(json.dumps(MOCK_POST_STATS,  ensure_ascii=False), encoding="utf-8")
    mgpt_path.write_text(json.dumps(MOCK_MATCHGPT_T07, ensure_ascii=False), encoding="utf-8")

    script = SCRIPT_DIR / "exp_1_indicator3_prepost.py"
    ok, output = run_test("indicator3", [
        PYTHON, str(script),
        "--pre_stats",      str(pre_path),
        "--post_stats",     str(post_path),
        "--matchgpt_final", str(mgpt_path),
        "--output",         str(out_path),
    ], SCRIPT_DIR)

    check(ok, f"腳本執行成功（exit 0）：\n    {output}")
    if not ok:
        print(f"    stderr: {output}")
        return

    check(out_path.exists(), "JSON 輸出檔案存在")
    md_path = out_path.with_suffix(".md")
    check(md_path.exists(), "Markdown 輸出檔案存在")

    data = json.loads(out_path.read_text(encoding="utf-8"))
    check("generated_at"  in data, "JSON 含 generated_at")
    check("stages"        in data, "JSON 含 stages")
    check("rows"          in data, "JSON 含 rows")
    check("matchgpt_extra" in data, "JSON 含 matchgpt_extra")

    rows = data["rows"]
    check(len(rows) == 6, f"rows 有 6 個指標（實際 {len(rows)}）")

    metric_keys = {r["metric"] for r in rows}
    expected = {"node_count", "rel_count", "wcc_count", "avg_degree",
                "isolated_ratio", "leiden_modularity_gamma1"}
    check(metric_keys == expected, f"rows 含全部 6 個指標鍵")

    for r in rows:
        check(r["pre_validation"]  != "N/A", f"{r['metric']}: pre 非空")
        check(r["post_validation"] != "N/A", f"{r['metric']}: post 非空")
        check(r["post_matchgpt"]   != "N/A", f"{r['metric']}: mgpt 非空")

    rel_row = next(r for r in rows if r["metric"] == "rel_count")
    check(rel_row["pre_validation"] == 5001,
          "relation_count 別名可映射到 rel_count（pre）")
    check(rel_row["post_matchgpt"] == 4760,
          "matchgpt post_merge relation_count 別名可映射到 rel_count")

    iso_row = next(r for r in rows if r["metric"] == "isolated_ratio")
    check(iso_row["pre_validation"] == 0.0,
          "isolated_node_ratio 別名可映射到 isolated_ratio（pre）")
    check(iso_row["post_matchgpt"] == 0.0,
          "matchgpt post_merge isolated_node_ratio 別名可映射到 isolated_ratio")

    # 手算驗證：節點數 Pre→Post 應為 -9.85%
    node_row = next(r for r in rows if r["metric"] == "node_count")
    diff_pct = (3703 - 4108) / 4108 * 100
    check(
        node_row["change_pre_to_post"] == f"{diff_pct:+.2f}%",
        f"節點數 Pre→Post 計算正確（預期 {diff_pct:+.2f}%，得 {node_row['change_pre_to_post']}）"
    )

    # Markdown 含必要區塊
    md = md_path.read_text(encoding="utf-8")
    for keyword in ["Pre-validation", "Post-validation", "Post-MatchGPT", "質性說明"]:
        check(keyword in md, f"Markdown 含 '{keyword}'")

    return out_path  # 供後續腳本使用


def test_indicator2(tmp: Path):
    print("\n[Test 2] exp_1_indicator2_matchgpt.py")

    summary_path  = tmp / "matchgpt_3layer_summary.json"
    decisions_path = tmp / "matchgpt_decisions.csv"
    out_path       = tmp / "indicator2_matchgpt_metrics.json"

    summary_path.write_text(json.dumps(MOCK_SUMMARY, ensure_ascii=False), encoding="utf-8")

    with open(decisions_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name_a", "type_a", "name_b", "type_b",
                         "similarity", "decision", "confidence", "reason"])
        for row in MOCK_DECISIONS_ROWS:
            writer.writerow(row)

    script = SCRIPT_DIR / "exp_1_indicator2_matchgpt.py"
    ok, output = run_test("indicator2", [
        PYTHON, str(script),
        "--summary",   str(summary_path),
        "--decisions", str(decisions_path),
        "--output",    str(out_path),
    ], SCRIPT_DIR)

    check(ok, f"腳本執行成功（exit 0）：\n    {output}")
    if not ok:
        print(f"    stderr: {output}")
        return

    check(out_path.exists(), "JSON 輸出檔案存在")
    md_path = out_path.with_suffix(".md")
    check(md_path.exists(), "Markdown 輸出檔案存在")

    data = json.loads(out_path.read_text(encoding="utf-8"))
    check("threshold" in data, "JSON 含 prompt 規格 key: threshold")
    check("structural" in data, "JSON 含 prompt 規格 key: structural")
    check("ontology_consistency" in data, "JSON 含 prompt 規格 key: ontology_consistency")
    check("sensitivity" in data, "JSON 含 prompt 規格 key: sensitivity")
    check("layer1_structural"          in data, "JSON 含 layer1_structural")
    check("layer2_ontology_consistency" in data, "JSON 含 layer2_ontology_consistency")
    check("layer3_parameter_sensitivity" in data, "JSON 含 layer3_parameter_sensitivity")

    check(data.get("threshold") == ["t0.5", "t0.7", "t0.9"],
          f"threshold 正規化為 t0.5/t0.7/t0.9（實際 {data.get('threshold')}）")
    check(len(data.get("structural", [])) == 3,
          f"structural 有 3 個 threshold 列（實際 {len(data.get('structural', []))}）")
    check(len(data.get("ontology_consistency", [])) == 3,
          f"ontology_consistency 有 3 個 threshold 列（實際 {len(data.get('ontology_consistency', []))}）")
    check(len(data.get("sensitivity", [])) == 3,
          f"sensitivity 有 3 個 pairwise 比較列（實際 {len(data.get('sensitivity', []))}）")

    check(len(data["layer1_structural"]) == 3,
          f"layer1 有 3 個 threshold 列（實際 {len(data['layer1_structural'])}）")
    check(len(data["layer2_ontology_consistency"]) == 3,
          f"layer2 有 3 個 threshold 列（實際 {len(data['layer2_ontology_consistency'])}）")
    check(len(data["layer3_parameter_sensitivity"]) == 3,
          f"layer3 有 3 個敏感性比較列（實際 {len(data['layer3_parameter_sensitivity'])}）")

    # 驗證空值標示
    for row in data["layer1_structural"]:
        check(row["node_count"] != "N/A",
              f"layer1 {row['threshold']} node_count 有值")
        check(row["node_reduction_ratio_pct"].endswith("%"),
              f"layer1 {row['threshold']} node_reduction_ratio_pct 為百分比格式")

    for row in data["layer2_ontology_consistency"]:
        check(row["cross_type_merge_rate_pct"].endswith("%"),
              f"layer2 {row['threshold']} cross_type_merge_rate_pct 格式正確")

    # Markdown 含三層標記
    md = md_path.read_text(encoding="utf-8")
    for keyword in ["第一層", "第二層", "第三層", "節點縮減比", "關係保留率", "參數敏感性"]:
        check(keyword in md, f"Markdown 含 '{keyword}'")

    return out_path


def test_table47_assemble(tmp: Path, ind2_path: Path, ind3_path: Path):
    print("\n[Test 3] exp_1_table47_assemble.py")

    out_path = tmp / "表4-7草稿.md"

    script = SCRIPT_DIR / "exp_1_table47_assemble.py"
    ok, output = run_test("table47", [
        PYTHON, str(script),
        "--indicator2", str(ind2_path),
        "--indicator3", str(ind3_path),
        "--output",     str(out_path),
    ], SCRIPT_DIR)

    check(ok, f"腳本執行成功（exit 0）：\n    {output}")
    if not ok:
        print(f"    stderr: {output}")
        return

    check(out_path.exists(), "Markdown 輸出檔案存在")

    md = out_path.read_text(encoding="utf-8")
    check(len(md) > 500, f"Markdown 長度合理（{len(md)} chars）")

    required_sections = [
        "Pre-validation",
        "Post-validation",
        "Post-MatchGPT",
        "第一層",
        "第二層",
        "第三層",
        "質性說明",
        "threshold",
    ]
    for s in required_sections:
        check(s in md, f"Markdown 含段落 '{s}'")

    table_lines = [l for l in md.splitlines() if l.startswith("|")]
    check(len(table_lines) >= 10, f"Markdown 表格行數足夠（{len(table_lines)} 行）")

    # 確認可解析：每個表格行 | 數應一致
    table_blocks = []
    current = []
    for line in md.splitlines():
        if line.startswith("|"):
            current.append(line)
        else:
            if current:
                table_blocks.append(current)
                current = []
    if current:
        table_blocks.append(current)

    for i, block in enumerate(table_blocks):
        col_counts = [len(line.split("|")) for line in block]
        check(
            len(set(col_counts)) == 1,
            f"表格 #{i+1} 各行欄位數一致（{col_counts[0]-2} 欄）"
        )


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("實驗 8.1 分析腳本 Mock 驗證")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="exp81_mock_") as tmp_str:
        tmp = Path(tmp_str)

        ind3_path = test_indicator3(tmp)
        ind2_path = test_indicator2(tmp)

        if ind2_path and ind3_path:
            test_table47_assemble(tmp, ind2_path, ind3_path)
        else:
            print("\n[Test 3] SKIP（前兩個測試未產出輸出檔案）")

    print("\n" + "=" * 60)
    print(f"結果：{PASS_COUNT} 通過 / {FAIL_COUNT} 失敗")
    print("=" * 60)

    sys.exit(0 if FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()
