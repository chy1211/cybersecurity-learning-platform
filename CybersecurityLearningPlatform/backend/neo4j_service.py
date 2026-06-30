from neo4j import GraphDatabase
from config import Config
import re


def _parse_chapter_file(raw):
    if not raw or not isinstance(raw, str):
        return None
    match = re.search(r"第\s*0*(\d+)章\s*([^_.]*?)(?:[_-].*)?(?:\.pdf)?$", raw)
    if not match:
        return None
    try:
        number = int(match.group(1))
    except Exception:
        return None
    title = (match.group(2) or "").strip()
    return {"number": number, "title": title}


def _parse_exercise_file(raw):
    if not raw or not isinstance(raw, str):
        return None
    match = re.search(r"ch\s*0*(\d+)[_-]*\s*習題解答(?:\.pdf)?$", raw, re.IGNORECASE)
    if not match:
        return None
    try:
        number = int(match.group(1))
    except Exception:
        return None
    return {"number": number}


def _parse_module_file(raw):
    if not raw or not isinstance(raw, str):
        return None
    match = re.search(r"模組\s*0*(\d+)[^.]*?(?=\.pdf|$)", raw)
    if not match:
        return None
    try:
        number = int(match.group(1))
    except Exception:
        return None
    return {"number": number}


def normalize_chapter_module_unit(raw):
    """Return a stable counting key for chapter/module source files."""
    chapter = _parse_chapter_file(raw)
    if chapter:
        if chapter["number"] < 1:
            return None
        return f"CH{chapter['number']:02d}"

    exercise = _parse_exercise_file(raw)
    if exercise:
        if exercise["number"] < 1:
            return None
        return f"CH{exercise['number']:02d}"

    module = _parse_module_file(raw)
    if module:
        if module["number"] < 1:
            return None
        return f"MOD{module['number']:02d}"

    return None


def count_chapter_modules(raw_units):
    keys = set()
    for raw in raw_units:
        key = normalize_chapter_module_unit(raw)
        if key:
            keys.add(key)
    return len(keys)


class Neo4jService:
    def __init__(self):
        self.driver = GraphDatabase.driver(Config.NEO4J_URI, auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD))
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def get_entity_context(self, entity_name):
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e {name: $entity_name})
                OPTIONAL MATCH (e)-[r]-(neighbor)
                RETURN e.name AS entity, e.description AS description,
                       collect({name: neighbor.name, description: neighbor.description, relationship: type(r)}) AS neighbors
                """,
                entity_name=entity_name
            )
            record = result.single()
            if not record:
                return None
            return {
                "entity": record["entity"],
                "description": record["description"],
                "neighbors": [n for n in record["neighbors"] if n["name"] is not None]
            }
    
    def get_skill_tree_data(self):
        """更新：使用 analysis_topological_layer 決定層級，並以原始關係呈現連線"""
        import random
        with self.driver.session() as session:
            # 獲取節點，使用 analysis_topological_layer 作為 level
            nodes_result = session.run("""
                MATCH (n)
                WHERE n.content_type = 'course' AND n.analysis_topological_layer IS NOT NULL
                RETURN n.name AS id, n.name AS label, n.analysis_topological_layer AS level,
                       n.analysis_centrality_degree AS size,
                       n.final_community AS community,
                       n.top_3_units AS top_3_units
                ORDER BY n.analysis_topological_layer, n.name
            """)
            nodes = []
            for record in nodes_result:
                level = record["level"]
                nodes.append({
                    "id": record["id"],
                    "data": {
                        "label": record["label"], 
                        "level": level, 
                        "unlocked": level == 0,
                        "community": record["community"],
                        "top_3_units": record["top_3_units"]
                    },
                    "position": {"x": random.randint(0, 800), "y": level * 150},
                    "type": "default"
                })
            
            # 獲取邊：僅保留從 低layer 指向 高layer 的原始關係
            edges_result = session.run("""
                MATCH (s)-[r]->(t)
                WHERE s.content_type = 'course' AND t.content_type = 'course'
                  AND s.analysis_topological_layer < t.analysis_topological_layer
                RETURN s.name AS source, t.name AS target, type(r) AS rel
            """)
            edges = []
            for i, record in enumerate(edges_result):
                edges.append({
                    "id": f"e{i}", 
                    "source": record["source"], 
                    "target": record["target"], 
                    "label": record["rel"],
                    "type": "smoothstep"
                })
            return {"nodes": nodes, "edges": edges}
    
    def search_entities(self, query):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e)
                WHERE e.name CONTAINS $search_query OR e.description CONTAINS $search_query
                RETURN e.name AS name
                LIMIT 5
            """, search_query=query)
            return [record["name"] for record in result]
    


    def batch_update_node_properties(self, updates):
        """批量更新節點屬性 (UNWIND 模式優化效能)"""
        with self.driver.session() as session:
            session.run("""
                UNWIND $updates AS update
                MATCH (n {name: update.name})
                SET n += update.properties
            """, updates=updates)

    def get_raw_knowledge_graph_full(self):
        """獲取完整圖譜結構供 Python 記憶體處理"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)-[r]->(m)
                RETURN n.name AS source, type(r) AS relationship, m.name AS target
            """)
            return [{"source": r["source"], "relationship": r["relationship"], "target": r["target"]} for r in result]


    def get_raw_knowledge_graph(self, limit=5000):
        """Task 5: 獲取全知識圖譜 (包含所有節點與關係)"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)-[r]->(m)
                RETURN n.name AS source, labels(n)[0] AS source_type, type(r) AS relationship, m.name AS target, labels(m)[0] AS target_type
                LIMIT $limit
            """, limit=limit)
            
            nodes_dict = {}
            edges = []
            
            for record in result:
                source = record["source"]
                source_type = record["source_type"]
                target = record["target"]
                target_type = record["target_type"]
                rel = record["relationship"]
                
                if source not in nodes_dict:
                    nodes_dict[source] = {"id": source, "label": source, "type": source_type}
                if target not in nodes_dict:
                    nodes_dict[target] = {"id": target, "label": target, "type": target_type}
                
                edges.append({
                    "source": source,
                    "target": target,
                    "relationship": rel
                })
                
            formatted_nodes = list(nodes_dict.values())
            return {"nodes": formatted_nodes, "edges": edges}

    def get_overview_stats(self):
        with self.driver.session() as session:
            node_result = session.run("""
                MATCH (n)
                RETURN count(n) AS node_count
            """)
            node_record = node_result.single()

            edge_result = session.run("""
                MATCH ()-[r]->()
                RETURN count(r) AS edge_count
            """)
            edge_record = edge_result.single()

            community_result = session.run("""
                MATCH (n)
                WHERE n.communityId IS NOT NULL
                RETURN count(DISTINCT n.communityId) AS community_count
            """)
            community_record = community_result.single()

            # Fetch all units (like get_all_chapters) and build titleMap first
            chapters_result = session.run("""
                MATCH (n)
                WHERE n.source_file IS NOT NULL
                WITH n, CASE apoc.meta.cypher.type(n.source_file)
                    WHEN 'LIST OF STRING' THEN n.source_file
                    WHEN 'STRING' THEN [n.source_file]
                    ELSE []
                END AS source_files
                UNWIND source_files AS source_file
                RETURN source_file AS unit, count(DISTINCT n) AS node_count
                ORDER BY unit
            """)

            raw_units = [rec['unit'] for rec in chapters_result]
            chapter_count = count_chapter_modules(raw_units)

            return {
                "node_count": node_record["node_count"] if node_record else 0,
                "edge_count": edge_record["edge_count"] if edge_record else 0,
                "community_count": community_record["community_count"] if community_record else 0,
                "chapter_count": chapter_count
            }

    def get_node_neighbors(self, node_id, limit=20):
        """獲取特定節點的相鄰節點與關係"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)-[r]-(m)
                WHERE n.name = $node_id
                RETURN startNode(r).name AS source, type(r) AS relationship, endNode(r).name AS target
                LIMIT $limit
            """, node_id=node_id, limit=limit)
            
            relations = []
            for record in result:
                relations.append({
                    "source": record["source"],
                    "relationship": record["relationship"],
                    "target": record["target"]
                })
            return relations

    def get_all_chapters(self):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)
                WHERE n.source_file IS NOT NULL
                WITH n, CASE apoc.meta.cypher.type(n.source_file)
                    WHEN 'LIST OF STRING' THEN n.source_file
                    WHEN 'STRING' THEN [n.source_file]
                    ELSE []
                END AS source_files
                UNWIND source_files AS source_file
                RETURN source_file AS unit, count(DISTINCT n) AS node_count
                ORDER BY unit
            """)
            return [{"unit": record["unit"], "node_count": record["node_count"]} for record in result]

    def get_chapter_graph(self, unit, limit=None):
        with self.driver.session() as session:
            query = """
                MATCH (n)
                WHERE n.source_file IS NOT NULL
                WITH n, CASE apoc.meta.cypher.type(n.source_file)
                    WHEN 'LIST OF STRING' THEN n.source_file
                    WHEN 'STRING' THEN [n.source_file]
                    ELSE []
                END AS source_files
                WHERE $unit IN source_files
                RETURN n.name AS id,
                       coalesce(n.display_name, n.name) AS name,
                       $unit AS unit,
                       n.source_file AS source_files,
                       n.communityId AS final_community,
                       n.outDegree_inCommunity AS degree,
                       n.nodeLayerInCommunity AS layer,
                       labels(n) AS labels
                ORDER BY n.outDegree_inCommunity DESC, n.name
            """
            params = {"unit": unit}
            if limit is not None:
                query += "\nLIMIT $limit"
                params["limit"] = limit
            nodes_result = session.run(query, **params)
            
            nodes = []
            node_ids = set()
            for r in nodes_result:
                node_ids.add(r["id"])
                nodes.append({
                    "id": r["id"],
                    "name": r["name"],
                    "val": r["degree"] or 1,
                    "degree": r["degree"],
                    "unit_mentions": 1,
                    "layer": r["layer"],
                    "labels": r["labels"],
                    "top_3_units": r["source_files"],
                    "final_community": r["final_community"]
                })
                
            links = []
            if node_ids:
                links_result = session.run("""
                    MATCH (n)-[r]->(m)
                    WHERE n.name IN $node_ids AND m.name IN $node_ids
                    RETURN n.name AS source, m.name AS target, type(r) AS type
                """, node_ids=list(node_ids))
                for r in links_result:
                    links.append({
                        "source": r["source"],
                        "target": r["target"],
                        "type": r["type"],
                        "name": r["type"]
                    })
            
            return {"nodes": nodes, "links": links}

    def get_all_communities(self):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)
                WHERE n.communityId IS NOT NULL
                WITH n.communityId AS community, count(n) AS size
                ORDER BY size DESC, community ASC
                RETURN community, size
            """)
            return [{"community": record["community"], "size": record["size"]} for record in result]

    def get_community_graph(self, community, limit=None):
        with self.driver.session() as session:
            comm_val = int(community) if str(community).isdigit() else community
            query = """
                MATCH (n)
                WHERE n.communityId = $community
                RETURN n.name AS id,
                       coalesce(n.display_name, n.name) AS name,
                       n.source_file AS top_3_units,
                       n.communityId AS final_community,
                       n.outDegree_inCommunity AS degree,
                       n.betweenness_inCommunity AS betweenness,
                       n.nodeLayerInCommunity AS layer,
                       labels(n) AS labels
                ORDER BY n.outDegree_inCommunity DESC, n.name
            """
            params = {"community": comm_val}
            if limit is not None:
                query += "\nLIMIT $limit"
                params["limit"] = limit
            nodes_result = session.run(query, **params)
            
            nodes = []
            node_ids = set()
            for r in nodes_result:
                node_ids.add(r["id"])
                nodes.append({
                    "id": r["id"],
                    "name": r["name"],
                    "val": r["degree"] or 1,
                    "degree": r["degree"],
                    "betweenness": r["betweenness"],
                    "layer": r["layer"],
                    "labels": r["labels"],
                    "top_3_units": r["top_3_units"],
                    "final_community": r["final_community"]
                })
            
            links = []
            if node_ids:
                links_result = session.run("""
                    MATCH (n)-[r]->(m)
                    WHERE n.name IN $node_ids AND m.name IN $node_ids
                    RETURN n.name AS source, m.name AS target, type(r) AS type
                """, node_ids=list(node_ids))
                for r in links_result:
                    links.append({
                        "source": r["source"],
                        "target": r["target"],
                        "type": r["type"],
                        "name": r["type"]
                    })
            
            return {"nodes": nodes, "links": links}

    def get_community_learning_paths(self):
        """取得所有社群的學習路徑，按社群內 out-degree 排序節點"""
        with self.driver.session() as session:
            # 1. 各社群內節點的社群內 out-degree
            intra_result = session.run("""
                MATCH (n) WHERE n.communityId IS NOT NULL
                WITH n.communityId AS community, n.name AS node,
                     n.nodeLayerInCommunity AS layer,
                     n.outDegree_inCommunity AS outDegree
                ORDER BY community, outDegree DESC, node
                RETURN community, collect({
                    name: node,
                    outDegree: outDegree,
                    layer: layer
                }) AS nodes
            """)
            communities = {}
            for record in intra_result:
                comm_id = record["community"]
                communities[comm_id] = {
                    "community": comm_id,
                    "nodes": record["nodes"],
                    "size": len(record["nodes"])
                }

            # 2. 跨社群 out-degree（基礎程度排序）
            inter_result = session.run("""
                MATCH (a)-->(b)
                                WHERE a.communityId IS NOT NULL AND b.communityId IS NOT NULL
                                    AND a.communityId <> b.communityId
                                WITH a.communityId AS source_comm, count(*) AS interOutDegree
                ORDER BY interOutDegree DESC
                RETURN source_comm, interOutDegree
            """)
            inter_ranking = {}
            for i, record in enumerate(inter_result):
                inter_ranking[record["source_comm"]] = {
                    "interOutDegree": record["interOutDegree"],
                    "rank": i
                }

            # 3. 社群內部邊（供 dagre layout 使用）
            edges_result = session.run("""
                MATCH (a)-[r]->(b)
                                WHERE a.communityId IS NOT NULL
                                    AND a.communityId = b.communityId
                                RETURN a.communityId AS community,
                       a.name AS source, b.name AS target, type(r) AS rel
            """)
            comm_edges = {}
            for record in edges_result:
                cid = record["community"]
                if cid not in comm_edges:
                    comm_edges[cid] = []
                comm_edges[cid].append({
                    "source": record["source"],
                    "target": record["target"],
                    "rel": record["rel"]
                })

            # 合併結果
            result = []
            for comm_id, comm_data in communities.items():
                inter = inter_ranking.get(comm_id, {"interOutDegree": 0, "rank": 9999})
                comm_data["interOutDegree"] = inter["interOutDegree"]
                comm_data["rank"] = inter["rank"]
                comm_data["edges"] = comm_edges.get(comm_id, [])
                result.append(comm_data)

            result.sort(key=lambda x: x["rank"])
            return result

    def get_chapter_learning_paths(self):
        """取得所有章節的學習路徑，按章節內 out-degree 排序節點"""
        with self.driver.session() as session:
            # 1. 各章節內節點的章節內 out-degree
            intra_result = session.run("""
                MATCH (n) WHERE n.source_file IS NOT NULL
                WITH n, CASE apoc.meta.cypher.type(n.source_file)
                    WHEN 'LIST OF STRING' THEN n.source_file
                    WHEN 'STRING' THEN [n.source_file]
                    ELSE []
                END AS source_files
                UNWIND source_files AS chapter
                WITH chapter, n.name AS node, n.nodeLayerInCommunity AS layer,
                     n.outDegree_inCommunity AS outDegree
                ORDER BY chapter, outDegree DESC, node
                RETURN chapter, collect({
                    name: node,
                    outDegree: outDegree,
                    layer: layer
                }) AS nodes
            """)
            chapters = {}
            for record in intra_result:
                ch_id = record["chapter"]
                chapters[ch_id] = {
                    "community": ch_id, # Reusing the 'community' key name for frontend compatibility
                    "nodes": record["nodes"],
                    "size": len(record["nodes"])
                }

            # 2. 跨章節 out-degree（基礎程度排序）
            inter_result = session.run("""
                MATCH (a)-[]->(b)
                     WHERE a.source_file IS NOT NULL AND b.source_file IS NOT NULL
                     WITH a, b,
                            CASE apoc.meta.cypher.type(a.source_file)
                                WHEN 'LIST OF STRING' THEN a.source_file
                                WHEN 'STRING' THEN [a.source_file]
                                ELSE []
                            END AS a_files,
                            CASE apoc.meta.cypher.type(b.source_file)
                                WHEN 'LIST OF STRING' THEN b.source_file
                                WHEN 'STRING' THEN [b.source_file]
                                ELSE []
                            END AS b_files
                     UNWIND a_files AS source_comm
                     UNWIND b_files AS target_comm
                     WITH source_comm, target_comm
                     WHERE source_comm <> target_comm
                     WITH source_comm, count(*) AS interOutDegree
                ORDER BY interOutDegree DESC
                RETURN source_comm, interOutDegree
            """)
            inter_ranking = {}
            for i, record in enumerate(inter_result):
                inter_ranking[record["source_comm"]] = {
                    "interOutDegree": record["interOutDegree"],
                    "rank": i
                }

            # 3. 章節內部邊（供 dagre layout 使用）
            edges_result = session.run("""
                MATCH (a)-[r]->(b)
                     WHERE a.source_file IS NOT NULL AND b.source_file IS NOT NULL
                     WITH a, b, r,
                            CASE apoc.meta.cypher.type(a.source_file)
                                WHEN 'LIST OF STRING' THEN a.source_file
                                WHEN 'STRING' THEN [a.source_file]
                                ELSE []
                            END AS a_files,
                            CASE apoc.meta.cypher.type(b.source_file)
                                WHEN 'LIST OF STRING' THEN b.source_file
                                WHEN 'STRING' THEN [b.source_file]
                                ELSE []
                            END AS b_files
                     UNWIND a_files AS chapter
                     WITH a, b, r, chapter, b_files
                     WHERE chapter IN b_files
                     RETURN chapter AS community,
                       a.name AS source, b.name AS target, type(r) AS rel
            """)
            comm_edges = {}
            for record in edges_result:
                cid = record["community"]
                if cid not in comm_edges:
                    comm_edges[cid] = []
                comm_edges[cid].append({
                    "source": record["source"],
                    "target": record["target"],
                    "rel": record["rel"]
                })

            # 合併結果
            result = []
            for comm_id, comm_data in chapters.items():
                inter = inter_ranking.get(comm_id, {"interOutDegree": 0, "rank": 9999})
                comm_data["interOutDegree"] = inter["interOutDegree"]
                comm_data["rank"] = inter["rank"]
                comm_data["edges"] = comm_edges.get(comm_id, [])
                result.append(comm_data)

            result.sort(key=lambda x: x["rank"])
            return result

    def plan_learning_path(self, target_node, learned_nodes, mode='community'):
        """根據已學節點和目標節點，用反向 BFS 規劃學習路徑"""
        with self.driver.session() as session:
            # 確認目標節點存在
            check = session.run("MATCH (n {name: $name}) RETURN n.name AS name", name=target_node)
            target_record = check.single()
            if not target_record:
                return {"error": "目標節點不存在", "path": []}

            # 取得所有 prerequisite 邊（低 layer → 高 layer）
            edges_result = session.run("""
                MATCH (s)-[r]->(t)
                                WHERE s.nodeLayerInCommunity IS NOT NULL
                                    AND t.nodeLayerInCommunity IS NOT NULL
                RETURN s.name AS source, t.name AS target
            """)
            # 建立反向鄰接表（target → sources）
            reverse_adj = {}
            for record in edges_result:
                t = record["target"]
                s = record["source"]
                if t not in reverse_adj:
                    reverse_adj[t] = []
                reverse_adj[t].append(s)

            # BFS 反向追蹤：從目標節點往前找先備知識
            learned_set = set(learned_nodes or [])
            visited = set()
            path_nodes = []
            queue = [target_node]
            parent = {target_node: None}

            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                path_nodes.append(current)

                # 如果已學會就不再往前追蹤
                if current in learned_set and current != target_node:
                    continue

                for prereq in reverse_adj.get(current, []):
                    if prereq not in visited:
                        queue.append(prereq)
                        if prereq not in parent:
                            parent[prereq] = current

            # 取得路徑上所有節點的詳細資訊
            if not path_nodes:
                return {"path": [], "target": target_node}

            if mode == 'chapter':
                nodes_result = session.run("""
                    MATCH (n) WHERE n.name IN $names
                    WITH n, CASE apoc.meta.cypher.type(n.source_file)
                        WHEN 'LIST OF STRING' THEN n.source_file
                        WHEN 'STRING' THEN [n.source_file]
                        ELSE []
                    END AS source_files
                    WITH n.name AS name,
                         head(source_files) AS community,
                         n.nodeLayerInCommunity AS layer,
                         n.outDegree_inCommunity AS outDegree
                    RETURN name, community, layer, outDegree
                """, names=path_nodes)
            else:
                nodes_result = session.run("""
                    MATCH (n) WHERE n.name IN $names
                    RETURN n.name AS name,
                           n.communityId AS community,
                           n.nodeLayerInCommunity AS layer,
                           n.outDegree_inCommunity AS outDegree
                """, names=path_nodes)

            node_info = {}
            for record in nodes_result:
                node_info[record["name"]] = {
                    "name": record["name"],
                    "community": record["community"],
                    "layer": record["layer"],
                    "outDegree": record["outDegree"],
                    "learned": record["name"] in learned_set
                }

            # 按 layer 升序排列（先學基礎）
            ordered_path = sorted(
                [node_info[n] for n in path_nodes if n in node_info],
                key=lambda x: (x.get("layer") or 0, -(x.get("outDegree") or 0))
            )

            return {
                "path": ordered_path,
                "target": target_node,
                "total": len(ordered_path),
                "already_learned": sum(1 for n in ordered_path if n["learned"]),
                "to_learn": sum(1 for n in ordered_path if not n["learned"])
            }

    def search_nodes_by_name(self, query, limit=15, mode='community'):
        """模糊搜尋節點名稱（供 autocomplete 使用）"""
        with self.driver.session() as session:
            if mode == 'chapter':
                result = session.run("""
                    MATCH (n)
                    WHERE n.name CONTAINS $q AND n.source_file IS NOT NULL
                    WITH n, CASE apoc.meta.cypher.type(n.source_file)
                        WHEN 'LIST OF STRING' THEN n.source_file
                        WHEN 'STRING' THEN [n.source_file]
                        ELSE []
                    END AS source_files
                    UNWIND source_files AS community
                    RETURN n.name AS name, community,
                           n.nodeLayerInCommunity AS layer
                    ORDER BY size(n.name)
                    LIMIT $lim
                """, q=query, lim=limit)
            else:
                result = session.run("""
                    MATCH (n)
                    WHERE n.name CONTAINS $q AND n.communityId IS NOT NULL
                    RETURN n.name AS name, n.communityId AS community,
                           n.nodeLayerInCommunity AS layer
                    ORDER BY size(n.name)
                    LIMIT $lim
                """, q=query, lim=limit)
            
            seen = set()
            nodes = []
            for r in result:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    nodes.append({"name": r["name"], "community": r["community"], "layer": r["layer"]})
            return nodes
