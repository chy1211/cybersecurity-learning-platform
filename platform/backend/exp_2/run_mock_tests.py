#!/usr/bin/env python3
"""Mock verification for experiment 2 Leiden three-layer validation scripts."""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
PYTHON = sys.executable

PASS_COUNT = 0
FAIL_COUNT = 0


def check(condition: bool, message: str) -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        print(f"  PASS: {message}")
        PASS_COUNT += 1
    else:
        print(f"  FAIL: {message}")
        FAIL_COUNT += 1


def run(args: list[str], cwd: Path = SCRIPT_DIR) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", capture_output=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_close(actual: float, expected: float, message: str, tol: float = 1e-6) -> None:
    check(abs(actual - expected) <= tol, f"{message} (expected={expected:.6f}, actual={actual:.6f})")


def write_mock_leiden_compare(path: Path) -> None:
    data = [
        {
            "label": "gamma_1",
            "gamma": 1.0,
            "minCommunitySize": None,
            "modularity": 0.7312,
            "communityCount": 5,
            "sizeDistribution": {"1": 1, "2": 2, "5": 1, "12": 1},
        },
        {
            "label": "gamma_2",
            "gamma": 2.0,
            "minCommunitySize": None,
            "modularity": 0.7688,
            "communityCount": 4,
            "communitySizes": [8, 7, 3, 2],
        },
        {
            "label": "gamma_2_min3",
            "gamma": 2.0,
            "minCommunitySize": 3,
            "modularity": 0.7811,
            "communityCount": 3,
            "sizeDistribution": [9, 6, 6],
        },
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_layer1(base_dir: Path) -> Path:
    print("\n[layer1_algorithm]")
    td_path = base_dir / "layer1"
    td_path.mkdir(parents=True, exist_ok=True)
    input_path = td_path / "leiden_3params_compare.json"
    output_json = td_path / "layer1_algorithm_metrics.json"
    output_plot = td_path / "layer1_size_distribution.png"
    write_mock_leiden_compare(input_path)

    cp = run([
        PYTHON,
        "exp_2_layer1_algorithm.py",
        "--leiden_compare",
        str(input_path),
        "--output_json",
        str(output_json),
        "--output_plot",
        str(output_plot),
    ])
    check(cp.returncode == 0, f"CLI exits successfully\n    {cp.stderr.strip() or cp.stdout.strip()}")
    check(output_json.exists(), "metrics JSON is written")
    check(output_plot.exists() and output_plot.stat().st_size > 0, "size distribution plot is written")
    md_path = output_json.with_suffix(".md")
    check(md_path.exists() and "第一層" in md_path.read_text(encoding="utf-8"), "Markdown companion is written")

    data = load_json(output_json)
    rows = data["table_rows"]
    check(len(rows) == 3, "three Leiden configurations are summarized")
    first = rows[0]
    check(first["community_count"] == 5, "dict sizeDistribution expands to community_count")
    check(first["largest_community_size"] == 12, "largest community size is computed")
    assert_close(first["average_community_size"], 4.4, "average community size is weighted")
    check(rows[2]["min_community_size"] == 3, "minCommunitySize is preserved")
    check(data["selected_config"]["label"] == "gamma_2_min3", "highest modularity row is selected")
    return output_json


def write_mock_chapter_yaml(path: Path) -> None:
    path.write_text(
        "\n".join([
            "ch1.pdf:",
            "  chapter_unit: 第01章 資訊安全",
            "ch2.pdf:",
            "  chapter_unit: 第02章 電子商務安全",
            "ch3.pdf:",
            "  chapter_unit: 第03章 實體安全",
            "",
        ]),
        encoding="utf-8",
    )


def write_mock_ccod(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["cid", "ccod", "rank", "community_size"])
        writer.writerow([2, 0.91, 1, 3])
        writer.writerow([3, 0.62, 2, 3])
        writer.writerow([1, 0.55, 3, 4])


def test_layer3(base_dir: Path) -> tuple[Path, Path]:
    print("\n[layer3_task]")
    td_path = base_dir / "layer3"
    td_path.mkdir(parents=True, exist_ok=True)
    chapter_yaml = td_path / "source_file_to_chapter.yaml"
    ccod = td_path / "ccod_ranking.csv"
    dominant = td_path / "layer3_dominant_chapter.json"
    topn = td_path / "layer3_topn_coverage.json"
    plot = td_path / "layer3_topn_coverage_curve.png"
    write_mock_chapter_yaml(chapter_yaml)
    write_mock_ccod(ccod)

    cp = run([
        PYTHON,
        "exp_2_layer3_task.py",
        "--mock_neo4j",
        "--chapter_dict",
        str(chapter_yaml),
        "--ccod_ranking",
        str(ccod),
        "--output_dominant",
        str(dominant),
        "--output_topn",
        str(topn),
        "--output_plot",
        str(plot),
    ])
    check(cp.returncode == 0, f"CLI exits successfully\n    {cp.stderr.strip() or cp.stdout.strip()}")
    check(dominant.exists(), "dominant chapter JSON is written")
    check(topn.exists(), "top-N coverage JSON is written")
    check(plot.exists() and plot.stat().st_size > 0, "coverage curve plot is written")

    dominant_data = load_json(dominant)
    summary = dominant_data["summary"]
    assert_close(summary["mean_dominant_ratio"], (0.75 + 2 / 3 + 2 / 3) / 3, "dominant ratio mean")
    assert_close(summary["median_dominant_ratio"], 2 / 3, "dominant ratio median")
    assert_close(summary["ge_70_ratio"], 1 / 3, "dominant ratio >=70% share")

    topn_data = load_json(topn)
    assert_close(topn_data["summary"]["size_desc"]["n1"], 1 / 3, "size-desc N=1 average coverage")
    assert_close(topn_data["summary"]["ccod_rank"]["n1"], 0.25, "CCOD-rank N=1 average coverage")
    assert_close(topn_data["curves"]["ccod_rank"]["average_curve"]["2"], 2 / 3, "CCOD-rank N=2 average coverage")
    assert_close(topn_data["summary"]["size_desc"]["n3"], 1.0, "size-desc N=3 average coverage")
    return dominant, topn


def test_layer2_method1(base_dir: Path) -> Path:
    print("\n[layer2_method1_enrichment]")
    td_path = base_dir / "layer2_method1"
    td_path.mkdir(parents=True, exist_ok=True)
    output_json = td_path / "layer2_method1_enrichment.json"
    output_heatmap = td_path / "layer2_method1_enrichment_heatmap.png"
    output_md = td_path / "layer2_method1_summary.md"

    cp = run([
        PYTHON,
        "exp_2_layer2_method1.py",
        "--mock_neo4j",
        "--min_size",
        "5",
        "--output_json",
        str(output_json),
        "--output_heatmap",
        str(output_heatmap),
        "--output_md",
        str(output_md),
    ])
    check(cp.returncode == 0, f"CLI exits successfully\n    {cp.stderr.strip() or cp.stdout.strip()}")
    check(output_json.exists(), "method1 JSON is written")
    check(output_heatmap.exists() and output_heatmap.stat().st_size > 0, "method1 heatmap is written")
    check(output_md.exists() and output_md.stat().st_size > 0, "method1 Markdown summary is written")

    data = load_json(output_json)
    check(data["parameters"]["min_community_size"] == 5, "method1 preserves min_size")
    check("entropy_summary" in data, "method1 reports entropy summary")
    check("enrichment_summary" in data, "method1 reports enrichment summary")
    return output_json


def test_layer2_method2(base_dir: Path) -> Path:
    print("\n[layer2_method2_embedding]")
    td_path = base_dir / "layer2_method2"
    td_path.mkdir(parents=True, exist_ok=True)
    pairs = td_path / "layer2_pairs.csv"
    output_json = td_path / "layer2_method2_results.json"
    emb_cache = td_path / "layer2_method2_embeddings_cache.json"

    cp = run([
        PYTHON,
        "exp_2_layer2_method2.py",
        "--mock_neo4j",
        "--mock_api",
        "--min_size",
        "5",
        "--pairs_per_community",
        "2",
        "--output_pairs",
        str(pairs),
        "--output_json",
        str(output_json),
        "--output_emb_cache",
        str(emb_cache),
    ])
    check(cp.returncode == 0, f"CLI exits successfully\n    {cp.stderr.strip() or cp.stdout.strip()}")
    check(pairs.exists(), "method2 pairs CSV is written")
    check(output_json.exists(), "method2 JSON is written")
    check(emb_cache.exists(), "method2 embedding cache is written")

    pair_rows = list(csv.DictReader(pairs.open(encoding="utf-8")))
    check(len(pair_rows) > 0, "method2 samples node pairs")
    check({r["pair_type"] for r in pair_rows} == {"in", "cross"}, "method2 outputs both in and cross pairs")

    data = load_json(output_json)
    check(data["parameters"]["min_community_size"] == 5, "method2 preserves min_size")
    check(data["parameters"]["pairs_per_community"] == 2, "method2 preserves pairs_per_community")
    check(data["parameters"]["embedding_model"] == "mock-embedding-model", "method2 uses mock embedding model")
    for key in ["mean_in", "mean_cross", "mean_diff", "cohen_d"]:
        check(key in data["statistics"], f"method2 statistics include {key}")
    return output_json


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="exp83_mock_") as td:
        base_dir = Path(td)
        test_layer1(base_dir)
        dominant, topn = test_layer3(base_dir)
        test_layer2_method1(base_dir)
        test_layer2_method2(base_dir)
    print(f"\nMock checks: {PASS_COUNT} passed / {FAIL_COUNT} failed")
    return 1 if FAIL_COUNT else 0


if __name__ == "__main__":
    raise SystemExit(main())
