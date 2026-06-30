#!/usr/bin/env python3
"""
Phase 2 Step 2.4: 社群內拓樸分層（雙方法比較實驗）

方法一：Centrality-based（選定正式方法）
  - 依社群內出度（in-community out-degree）分層
  - 同出度 = 同 layer；最高出度組 = layer 0
  - 對應 Liu & Wen (2019) 之出度中心性理論
  - 寫入屬性：nodeLayerInCommunity

方法二：DirectedEdges / DAG（比較用）
  - networkx topological_generations，in-degree=0 的節點 = Layer 0
  - 對應 Course-prerequisite networks (2023) 方法
  - 寫入屬性：nodeLayerInCommunity_dag

兩份 Markdown 輸出供論文典型案例分析。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import networkx as nx

from phase2_common import (
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    batch_write,
    default_output_path,
    open_driver,
    write_csv,
)

CYCLE_FIELDNAMES = ["cid", "source_id", "source_name", "target_id", "target_name", "reason"]
MIN_EXAMPLE_SIZE = 10   # 論文典型案例：只挑此規模以上的社群
N_EXAMPLES       = 3    # 自動挑幾個典型案例


# ═══════════════════════════════════════════════════════════════════════════════
# 資料擷取
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_nodes_with_in_community_outdegree(session) -> dict[int, list[dict]]:
    """
    每個節點計算其在社群內的出度（只算同社群的出邊）。
    回傳 {cid: [{node_id, name, type, in_comm_outdegree}, ...]}
    """
    result = session.run("""
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        OPTIONAL MATCH (n)-[r]->(b:KGNode)
          WHERE b.communityId = n.communityId
        RETURN n.communityId AS cid,
               id(n)         AS node_id,
               n.name        AS node_name,
               n.type        AS node_type,
               count(r)      AS out_deg
        ORDER BY cid, out_deg DESC, node_name
    """)
    communities: dict[int, list[dict]] = defaultdict(list)
    for rec in result:
        communities[rec["cid"]].append({
            "node_id":  rec["node_id"],
            "name":     rec["node_name"],
            "type":     rec["node_type"],
            "out_deg":  int(rec["out_deg"]),
        })
    return dict(communities)


def fetch_intra_community_edges(session) -> dict[int, list[tuple]]:
    """回傳社群內有向邊 {cid: [(src_id, dst_id), ...]}"""
    result = session.run("""
        MATCH (a:KGNode)-[r]->(b:KGNode)
        WHERE a.communityId IS NOT NULL
          AND a.communityId = b.communityId
        RETURN a.communityId AS cid,
               id(a) AS src, id(b) AS dst
        ORDER BY cid
    """)
    edges: dict[int, list[tuple]] = defaultdict(list)
    for rec in result:
        edges[rec["cid"]].append((rec["src"], rec["dst"]))
    return dict(edges)


# ═══════════════════════════════════════════════════════════════════════════════
# 方法一：Centrality-based 分層
# ═══════════════════════════════════════════════════════════════════════════════

def centrality_layers(nodes: list[dict]) -> dict[int, int]:
    """
    node_id → layer（0 = 最高出度組 = 最基礎）
    相同出度 → 相同 layer。
    """
    distinct_degrees = sorted({n["out_deg"] for n in nodes}, reverse=True)
    degree_to_layer  = {deg: idx for idx, deg in enumerate(distinct_degrees)}
    return {n["node_id"]: degree_to_layer[n["out_deg"]] for n in nodes}


# ═══════════════════════════════════════════════════════════════════════════════
# 方法二：DAG 拓樸分層
# ═══════════════════════════════════════════════════════════════════════════════

def _choose_cycle_edge(graph: nx.DiGraph):
    candidates = list(nx.selfloop_edges(graph))
    for component in nx.strongly_connected_components(graph):
        if len(component) <= 1:
            continue
        comp = set(component)
        for s, t in graph.edges(comp):
            if t in comp:
                candidates.append((s, t))
    if not candidates:
        raise nx.NetworkXUnfeasible("no removable edge found")
    return min(candidates, key=lambda e: (
        graph.in_degree(e[1]), graph.out_degree(e[0]),
        str(e[0]), str(e[1])
    ))


def dag_layers(node_ids: list[int], edges: list[tuple]) -> tuple[dict[int, int], list[tuple]]:
    """
    node_id → layer（0 = in-degree 0 的節點 = DAG 起點）。
    回傳 (layers_dict, removed_edges)
    """
    g = nx.DiGraph()
    g.add_nodes_from(node_ids)
    g.add_edges_from(edges)
    removed = []
    while not nx.is_directed_acyclic_graph(g):
        s, t = _choose_cycle_edge(g)
        g.remove_edge(s, t)
        removed.append((s, t))
    layers = {}
    for layer_idx, gen in enumerate(nx.topological_generations(g)):
        for nid in gen:
            layers[nid] = layer_idx
    return layers, removed


# ═══════════════════════════════════════════════════════════════════════════════
# 寫回節點屬性
# ═══════════════════════════════════════════════════════════════════════════════

def write_centrality_layers(session, rows: list[dict]) -> int:
    cypher = """
    UNWIND $rows AS row
    MATCH (n) WHERE id(n) = row.node_id
    SET n.nodeLayerInCommunity = row.layer
    """
    return batch_write(session, cypher, rows)


def write_dag_layers(session, rows: list[dict]) -> int:
    cypher = """
    UNWIND $rows AS row
    MATCH (n) WHERE id(n) = row.node_id
    SET n.nodeLayerInCommunity_dag = row.layer
    """
    return batch_write(session, cypher, rows)


# ═══════════════════════════════════════════════════════════════════════════════
# Markdown 輸出（格式對應舊實驗文件）
# ═══════════════════════════════════════════════════════════════════════════════

def export_centrality_md(
    communities: dict[int, list[dict]],
    centrality_results: dict[int, dict[int, int]],
    output_path: Path,
) -> None:
    lines = [
        "# 基於中心性指標的拓樸分層 (Topological Stratification via Centrality)",
        "",
        "此方法依 Liu & Wen (2019) 之出度中心性理論。",
        "社群內出度越高的節點代表其知識被更多其他概念依賴，為較基礎之先修知識。",
        "",
        "## 各社群內的學習先後順序 (Intra-Community)",
        "",
    ]
    for cid in sorted(communities.keys()):
        nodes = communities[cid]
        if len(nodes) < 2:
            continue
        layers = centrality_results.get(cid, {})
        lines.append(f"### 社群 {cid}（共 {len(nodes)} 節點）")
        # 按出度分組
        by_deg: dict[int, list[str]] = defaultdict(list)
        for n in nodes:
            by_deg[n["out_deg"]].append(n["name"])
        for deg in sorted(by_deg.keys(), reverse=True):
            names = ", ".join(by_deg[deg])
            lines.append(f"- **Out-Degree {deg}** (越基礎的知識): {names}")
        lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def export_dag_md(
    communities: dict[int, list[dict]],
    dag_results: dict[int, dict[int, int]],
    id_to_name: dict[int, str],
    output_path: Path,
) -> None:
    lines = [
        "# 基於有向邊的拓樸分層 (Topological Stratification via Directed Edges)",
        "",
        "此方法依 Course-prerequisite networks (2023) 之有向無環圖 (DAG) 分層法。",
        "社群內入度為 0 的節點視為最基礎（Layer 0）。",
        "",
        "## 各社群內的學習先後順序 (Intra-Community)",
        "",
    ]
    for cid in sorted(communities.keys()):
        nodes = communities[cid]
        if len(nodes) < 2:
            continue
        node_ids = [n["node_id"] for n in nodes]
        layers   = dag_results.get(cid, {})
        if not layers:
            continue
        max_layer = max(layers.values())
        lines.append(f"### 社群 {cid}（共 {len(nodes)} 節點，{max_layer+1} 層）")
        by_layer: dict[int, list[str]] = defaultdict(list)
        for nid in node_ids:
            layer = layers.get(nid, 0)
            by_layer[layer].append(id_to_name.get(nid, str(nid)))
        for layer_idx in sorted(by_layer.keys()):
            names = ", ".join(by_layer[layer_idx])
            lines.append(f"- **Layer {layer_idx}**: {names}")
        lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def pick_examples(communities: dict[int, list[dict]],
                  centrality_results: dict[int, dict[int, int]],
                  id_to_name: dict[int, str], n: int) -> list[int]:
    """挑選最具代表性的社群 id（規模 ≥ MIN_EXAMPLE_SIZE，層數最多）。"""
    candidates = []
    for cid, nodes in communities.items():
        if len(nodes) < MIN_EXAMPLE_SIZE:
            continue
        layers = centrality_results.get(cid, {})
        n_layers = len({v for v in layers.values()})
        candidates.append((n_layers, len(nodes), cid))
    candidates.sort(reverse=True)
    return [c[2] for c in candidates[:n]]


# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

def execute(uri: str, user: str, password: str, min_size: int,
            cycle_log: Path, md_centrality: Path, md_dag: Path) -> None:

    driver = open_driver(uri, user, password)
    cycle_rows: list[dict] = []

    try:
        with driver.session() as session:
            print("[1/5] 擷取社群節點與社群內出度...")
            communities = fetch_nodes_with_in_community_outdegree(session)
            total_nodes = sum(len(v) for v in communities.values())
            print(f"  社群數：{len(communities)}，節點數：{total_nodes}")

            print("[2/5] 擷取社群內有向邊（DAG 方法用）...")
            comm_edges = fetch_intra_community_edges(session)
            id_to_name = {n["node_id"]: n["name"]
                          for nodes in communities.values() for n in nodes}

            # ── 方法一：Centrality ──────────────────────────────────────────
            print("[3/5] 計算 Centrality 分層並寫回節點...")
            cent_results: dict[int, dict[int, int]] = {}
            cent_rows: list[dict] = []
            for cid, nodes in communities.items():
                layer_map = centrality_layers(nodes)
                cent_results[cid] = layer_map
                for node_id, layer in layer_map.items():
                    cent_rows.append({"node_id": node_id, "layer": layer})
            write_centrality_layers(session, cent_rows)
            print(f"  已寫入 nodeLayerInCommunity：{len(cent_rows)} 節點")

            # ── 方法二：DAG ─────────────────────────────────────────────────
            print("[4/5] 計算 DAG 分層並寫回節點...")
            dag_results: dict[int, dict[int, int]] = {}
            dag_rows: list[dict] = []
            for cid, nodes in communities.items():
                if len(nodes) < min_size:
                    for n in nodes:
                        dag_rows.append({"node_id": n["node_id"], "layer": 0})
                    continue
                node_ids = [n["node_id"] for n in nodes]
                edges    = comm_edges.get(cid, [])
                layers, removed = dag_layers(node_ids, edges)
                dag_results[cid] = layers
                for node_id, layer in layers.items():
                    dag_rows.append({"node_id": node_id, "layer": layer})
                for src, dst in removed:
                    cycle_rows.append({
                        "cid": cid,
                        "source_id":   src, "source_name": id_to_name.get(src, ""),
                        "target_id":   dst, "target_name": id_to_name.get(dst, ""),
                        "reason": "cycle_break",
                    })
            write_dag_layers(session, dag_rows)
            print(f"  已寫入 nodeLayerInCommunity_dag：{len(dag_rows)} 節點")
            print(f"  循環切邊數：{len(cycle_rows)}")

        # ── 輸出 ────────────────────────────────────────────────────────────
        print("[5/5] 輸出 Markdown 比較文件與循環記錄...")
        export_centrality_md(communities, cent_results, md_centrality)
        print(f"  ✓ Centrality → {md_centrality}")
        export_dag_md(communities, dag_results, id_to_name, md_dag)
        print(f"  ✓ DirectedEdges → {md_dag}")
        write_csv(cycle_log, CYCLE_FIELDNAMES, cycle_rows)
        print(f"  ✓ 循環記錄 → {cycle_log}")

        # ── 典型案例提示 ─────────────────────────────────────────────────────
        examples = pick_examples(communities, cent_results, id_to_name, N_EXAMPLES)
        print(f"\n論文典型案例建議（規模≥{MIN_EXAMPLE_SIZE}，層數最多的前{N_EXAMPLES}個）：")
        for cid in examples:
            nodes = communities[cid]
            layers_cnt = len({v for v in cent_results.get(cid, {}).values()})
            dag_cnt = max(dag_results.get(cid, {0: 0}).values()) + 1 \
                      if cid in dag_results else "?"
            print(f"  社群 {cid}：{len(nodes)} 節點，"
                  f"Centrality {layers_cnt} 層 / DAG {dag_cnt} 層")

    finally:
        driver.close()

    print("\n✅ 步驟 2.4 完成")
    print(f"   正式屬性：nodeLayerInCommunity（Centrality 方法）")
    print(f"   比較屬性：nodeLayerInCommunity_dag（DAG 方法）")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--uri",      default=DEFAULT_NEO4J_URI)
    p.add_argument("--user",     default=DEFAULT_NEO4J_USER)
    p.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    p.add_argument("--min_size", type=int, default=3,
                   help="DAG 方法最小社群規模（Centrality 方法對所有社群都算）")
    p.add_argument("--cycle_log",
                   default=str(default_output_path("cycle_edges_removed.csv")))
    p.add_argument("--md_centrality",
                   default=str(default_output_path("Topological_Stratification_Centrality.md")))
    p.add_argument("--md_dag",
                   default=str(default_output_path("Topological_Stratification_DirectedEdges.md")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    execute(
        args.uri, args.user, args.password, args.min_size,
        Path(args.cycle_log),
        Path(args.md_centrality),
        Path(args.md_dag),
    )


if __name__ == "__main__":
    main()
