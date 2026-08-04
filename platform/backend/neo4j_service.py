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

    def check_readiness(self):
        try:
            self.driver.verify_connectivity()
            with self.driver.session() as session:
                record = session.run("RETURN 1 AS ok").single()
            return (bool(record and record["ok"] == 1), "ok")
        except Exception:
            return (False, "database_unavailable")
    
    def get_entity_context(self, entity_name):
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e {name: $entity_name})
                OPTIONAL MATCH (e)-[r]-(neighbor)
                RETURN e.name AS entity, e.description AS description, e.source_file AS entity_source,
                       collect({
                           name: neighbor.name,
                           description: neighbor.description,
                           relationship: type(r),
                           source_file: neighbor.source_file,
                           relation_source: r.source_file
                       }) AS neighbors
                """,
                entity_name=entity_name
            )
            record = result.single()
            if not record:
                return None
            neighbors = [n for n in record["neighbors"] if n["name"] is not None]
            def source_refs(value):
                if isinstance(value, list):
                    return [str(item) for item in value if item]
                return [str(value)] if value else []

            evidence = [
                {
                    "entity": record["entity"],
                    "relationship": neighbor["relationship"],
                    "neighbor": neighbor["name"],
                    "source": source_refs(
                        neighbor.get("relation_source") or neighbor.get("source_file") or record["entity_source"]
                    ),
                }
                for neighbor in neighbors
            ]
            return {
                "entity": record["entity"],
                "description": record["description"],
                "source_file": record["entity_source"],
                "neighbors": neighbors,
                "evidence": evidence,
            }

    @staticmethod
    def _as_source_list(value):
        """source_file 可能是字串或字串陣列，統一成 list。"""
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return [str(value)] if value else []

    @staticmethod
    def _select_seeds(candidates, max_seeds):
        """挑檢索種子，濾掉子字串巧合與過短的泛詞。

        search_entities 的 partial 比對是 CONTAINS，會讓 "tor" 命中 "active directory"、
        "history"；單字節點（如「牆」）也會因查詢包含它而拿到 80 分。兩者都會把
        無關鄰域灌進上下文，因此這裡再過一層。
        """
        if not candidates:
            return []
        best = max(int(c.get("score") or 0) for c in candidates)
        # 有夠強的命中（精確／查詢包含實體名）就不再收 60 分的模糊比對
        threshold = 80 if best >= 80 else 60
        filtered = [
            c for c in candidates
            if int(c.get("score") or 0) >= threshold and len((c.get("name") or "").strip()) >= 2
        ]
        return filtered[:max_seeds]

    def get_graph_rag_subgraph(self, query, max_seeds=3, max_edges=60):
        """以查詢命中的多個實體為種子，取其一跳鄰域組成子圖。

        回傳的 nodes/edges 就是實際餵進 LLM 的內容，供前端如實揭露「用了哪些圖」。
        """
        candidates = self.search_entities(query)
        if not candidates:
            return None
        seeds = self._select_seeds(candidates, max_seeds)
        if not seeds:
            return None
        seed_names = [c["name"] for c in seeds]
        seed_score = {c["name"]: c["score"] for c in seeds}

        with self.driver.session() as session:
            rows = session.run("""
                MATCH (s) WHERE s.name IN $seeds
                MATCH (s)-[r]-(m)
                RETURN startNode(r).name AS src, endNode(r).name AS dst,
                       type(r) AS rel_type, r.relation AS rel_label,
                       r.source_file AS rel_source,
                       startNode(r).type AS src_type, endNode(r).type AS dst_type,
                       m.name AS neighbor, m.type AS neighbor_type
                LIMIT 600
            """, seeds=seed_names)

            seed_set = set(seed_names)
            edge_map = {}
            node_types = {}
            for record in rows:
                src, dst = record["src"], record["dst"]
                if not src or not dst:
                    continue
                node_types.setdefault(src, record["src_type"])
                node_types.setdefault(dst, record["dst_type"])
                if record["neighbor"]:
                    node_types.setdefault(record["neighbor"], record["neighbor_type"])
                key = (src, record["rel_type"], dst)
                if key in edge_map:
                    continue
                both_seeds = src in seed_set and dst in seed_set
                edge_map[key] = {
                    "source": src,
                    "relation": record["rel_type"],
                    "relation_label": record["rel_label"] or record["rel_type"],
                    "target": dst,
                    "source_files": self._as_source_list(record["rel_source"]),
                    "links_two_seeds": both_seeds,
                    # 排序權重：連接兩個種子最相關，其次看種子本身的比對分數
                    "_rank": (
                        0 if both_seeds else 1,
                        -max(seed_score.get(src, 0), seed_score.get(dst, 0)),
                        record["rel_type"] or "",
                        src,
                        dst,
                    ),
                }

            all_edges = sorted(edge_map.values(), key=lambda e: e["_rank"])
            total_found = len(all_edges)

            # 每個種子輪流出邊：避免高連結度的種子（如「攻擊」）把額度吃光，
            # 讓每個命中的知識點都在上下文裡有代表性。
            buckets = {name: [] for name in seed_names}
            for edge in all_edges:
                owners = [n for n in (edge["source"], edge["target"]) if n in seed_set]
                owner = max(owners, key=lambda n: seed_score.get(n, 0)) if owners else seed_names[0]
                buckets[owner].append(edge)

            kept = []
            while len(kept) < max_edges and any(buckets.values()):
                progressed = False
                for name in seed_names:
                    if not buckets[name]:
                        continue
                    kept.append(buckets[name].pop(0))
                    progressed = True
                    if len(kept) >= max_edges:
                        break
                if not progressed:
                    break

            kept.sort(key=lambda e: e["_rank"])
            for edge in kept:
                edge.pop("_rank", None)

            used_names = set()
            for edge in kept:
                used_names.add(edge["source"])
                used_names.add(edge["target"])
            used_names.update(seed_names)

            nodes = sorted(
                (
                    {
                        "name": name,
                        "type": node_types.get(name) or "unknown",
                        "is_seed": name in seed_set,
                    }
                    for name in used_names
                ),
                key=lambda n: (not n["is_seed"], n["name"]),
            )

            return {
                "seeds": [
                    {
                        "name": c["name"],
                        "type": node_types.get(c["name"]) or "unknown",
                        "score": c["score"],
                        "match_type": c["match_type"],
                    }
                    for c in seeds
                ],
                "nodes": nodes,
                "edges": kept,
                "stats": {
                    "seed_count": len(seeds),
                    "node_count": len(nodes),
                    "edge_count": len(kept),
                    "total_edges_found": total_found,
                    "truncated": total_found > len(kept),
                },
                "retrieval": {
                    "mode": "multi_seed_one_hop",
                    "max_seeds": max_seeds,
                    "max_edges": max_edges,
                    "candidates_considered": len(candidates),
                },
            }

    @staticmethod
    def _extract_search_terms(query):
        if not isinstance(query, str):
            return []
        terms = re.findall(r"[A-Za-z][A-Za-z0-9+.#_-]{1,}|[\u4e00-\u9fff]{2,}", query.lower())
        return list(dict.fromkeys(term for term in terms if len(term.strip()) >= 2))[:12]

    def search_entities(self, query, limit=8, min_score=60):
        terms = self._extract_search_terms(query)
        if not terms:
            return []
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e)
                WHERE e.name IS NOT NULL AND (
                    toLower($search_query) CONTAINS toLower(e.name)
                    OR any(term IN $terms WHERE toLower(e.name) = term)
                    OR any(term IN $terms WHERE toLower(e.name) CONTAINS term)
                )
                WITH e, CASE
                    WHEN any(term IN $terms WHERE toLower(e.name) = term) THEN 100
                    WHEN toLower($search_query) CONTAINS toLower(e.name) THEN 80
                    ELSE 60
                END AS score
                RETURN e.name AS name, score,
                       CASE score WHEN 100 THEN 'exact' WHEN 80 THEN 'query_contains_name' ELSE 'partial' END AS match_type
                ORDER BY score DESC, size(e.name), toLower(e.name)
                LIMIT $limit
            """, search_query=query, terms=terms, limit=limit)
            candidates = [
                {"name": record["name"], "score": record["score"], "match_type": record["match_type"]}
                for record in result
                if int(record["score"] or 0) >= min_score
            ]
            return candidates
    


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
        """Return all nodes plus a bounded, explicitly counted relationship page."""
        with self.driver.session() as session:
            node_count_record = session.run("MATCH (n) RETURN count(n) AS total_nodes").single()
            edge_count_record = session.run("MATCH ()-[r]->() RETURN count(r) AS total_edges").single()
            node_result = session.run("""
                MATCH (n)
                RETURN elementId(n) AS id, coalesce(n.name, elementId(n)) AS label,
                       coalesce(n.type, labels(n)[0], 'unknown') AS type
                ORDER BY id
            """)
            edge_result = session.run("""
                MATCH (n)-[r]->(m)
                RETURN elementId(n) AS source, type(r) AS relationship, elementId(m) AS target
                ORDER BY elementId(r)
                LIMIT $limit
            """, limit=limit)
            nodes = [dict(record) for record in node_result]
            edges = [dict(record) for record in edge_result]
            total_nodes = int(node_count_record["total_nodes"] or 0) if node_count_record else 0
            total_edges = int(edge_count_record["total_edges"] or 0) if edge_count_record else 0
            return {
                "nodes": nodes,
                "edges": edges,
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "returned_nodes": len(nodes),
                "returned_edges": len(edges),
                "truncated": len(nodes) < total_nodes or len(edges) < total_edges,
            }

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
                       labels(n) AS labels,
                       n.type AS type
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
                    # 節點型別存在 n.type 屬性（B3 平台格式轉換後 label 僅 Entity/KGNode），
                    # 前端 getNeo4jNodeType 優先吃這個欄位來上色與統計
                    "type": r["type"],
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
                       labels(n) AS labels,
                       n.type AS type
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
                    # 同 get_chapter_graph：型別在 n.type，不在 label
                    "type": r["type"],
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

    @staticmethod
    def _analysis_state(coverage):
        eligible = int(coverage.get("community_node_count") or 0)
        analyzed = int(coverage.get("analysis_node_count") or 0)
        if eligible <= 0 or analyzed <= 0:
            return "unavailable"
        if analyzed < eligible:
            return "partial"
        return "complete"

    @classmethod
    def _analysis_unavailable(cls, coverage, message=None):
        state = cls._analysis_state(coverage)
        return {
            "status": "analysis_unavailable",
            "analysis_state": state,
            "message": message or "目前目標範圍尚未寫入完整的分群內中心性與分層分析結果。",
            "navigation_type": "exploratory_structure",
            "path": [],
            "items": [],
            **coverage,
        }

    @staticmethod
    def _analysis_coverage(session, mode="community", community=None, source_files=None):
        if mode == "chapter":
            if source_files is not None:
                record = session.run("""
                    MATCH (n)
                    WHERE n.source_file IS NOT NULL
                    WITH n, CASE apoc.meta.cypher.type(n.source_file)
                        WHEN 'LIST OF STRING' THEN n.source_file
                        WHEN 'STRING' THEN [n.source_file]
                        ELSE []
                    END AS node_files
                    WHERE any(unit IN node_files WHERE unit IN $source_files)
                    RETURN count(n) AS community_node_count,
                           sum(CASE WHEN n.outDegree_inCommunity IS NOT NULL
                                         AND n.nodeLayerInCommunity IS NOT NULL
                                    THEN 1 ELSE 0 END) AS analysis_node_count
                """, source_files=source_files).single()
            else:
                record = session.run("""
                    MATCH (n)
                    WHERE n.source_file IS NOT NULL
                    RETURN count(n) AS community_node_count,
                           sum(CASE WHEN n.outDegree_inCommunity IS NOT NULL
                                         AND n.nodeLayerInCommunity IS NOT NULL
                                    THEN 1 ELSE 0 END) AS analysis_node_count
                """).single()
        elif community is not None:
            record = session.run("""
                MATCH (n)
                WHERE n.communityId = $community
                RETURN count(n) AS community_node_count,
                       sum(CASE WHEN n.outDegree_inCommunity IS NOT NULL
                                     AND n.nodeLayerInCommunity IS NOT NULL
                                THEN 1 ELSE 0 END) AS analysis_node_count
            """, community=community).single()
        else:
            record = session.run("""
                MATCH (n)
                WHERE n.communityId IS NOT NULL
                RETURN count(n) AS community_node_count,
                       sum(CASE WHEN n.outDegree_inCommunity IS NOT NULL
                                     AND n.nodeLayerInCommunity IS NOT NULL
                                THEN 1 ELSE 0 END) AS analysis_node_count
            """).single()
        eligible = int(record["community_node_count"] or 0) if record else 0
        analyzed = int(record["analysis_node_count"] or 0) if record else 0
        return {
            "community_node_count": eligible,
            "analysis_node_count": analyzed,
            "analysis_coverage": (analyzed / eligible) if eligible else 0.0,
        }

    def get_community_learning_paths(self):
        """Return exploratory community structure only when analysis properties exist."""
        with self.driver.session() as session:
            coverage = self._analysis_coverage(session, "community")
            state = self._analysis_state(coverage)
            if state == "unavailable":
                return self._analysis_unavailable(coverage)
            groups_result = session.run("""
                MATCH (n)
                WHERE n.communityId IS NOT NULL
                  AND n.outDegree_inCommunity IS NOT NULL
                  AND n.nodeLayerInCommunity IS NOT NULL
                WITH n.communityId AS community, n.name AS node,
                     n.nodeLayerInCommunity AS layer,
                     n.outDegree_inCommunity AS outDegree
                ORDER BY community, layer, outDegree DESC, node
                RETURN community, collect({name: node, outDegree: outDegree, layer: layer}) AS nodes
            """)
            groups = [
                {
                    "community": record["community"],
                    "nodes": record["nodes"],
                    "size": len(record["nodes"]),
                }
                for record in groups_result
            ]
            return {
                "status": "partial" if state == "partial" else "ok",
                "analysis_state": state,
                "navigation_type": "exploratory_structure",
                "message": (
                    "目前僅顯示已完成分析的分群；未分析分群不會被視為空路徑。"
                    if state == "partial"
                    else "排序僅反映分群與連結結構，不代表經驗證之先備次序。"
                ),
                "groups": groups,
                **coverage,
            }

    def get_chapter_learning_paths(self):
        """Return exploratory chapter groupings only when analysis properties exist."""
        with self.driver.session() as session:
            coverage = self._analysis_coverage(session, "chapter")
            state = self._analysis_state(coverage)
            if state == "unavailable":
                return self._analysis_unavailable(coverage)
            groups_result = session.run("""
                MATCH (n)
                WHERE n.source_file IS NOT NULL
                  AND n.outDegree_inCommunity IS NOT NULL
                  AND n.nodeLayerInCommunity IS NOT NULL
                WITH n, CASE apoc.meta.cypher.type(n.source_file)
                    WHEN 'LIST OF STRING' THEN n.source_file
                    WHEN 'STRING' THEN [n.source_file]
                    ELSE []
                END AS source_files
                UNWIND source_files AS chapter
                WITH chapter, n.name AS node, n.nodeLayerInCommunity AS layer,
                     n.outDegree_inCommunity AS outDegree
                ORDER BY chapter, layer, outDegree DESC, node
                RETURN chapter AS community,
                       collect({name: node, outDegree: outDegree, layer: layer}) AS nodes
            """)
            groups = [
                {
                    "community": record["community"],
                    "nodes": record["nodes"],
                    "size": len(record["nodes"]),
                }
                for record in groups_result
            ]
            return {
                "status": "partial" if state == "partial" else "ok",
                "analysis_state": state,
                "navigation_type": "exploratory_structure",
                "message": (
                    "目前僅顯示已完成分析的章節節點；未分析節點不會被視為空路徑。"
                    if state == "partial"
                    else "排序僅反映章節與連結結構，不代表經驗證之先備次序。"
                ),
                "groups": groups,
                **coverage,
            }

    def plan_learning_path(self, target_node, learned_nodes, mode='community'):
        """Return a target-scoped exploratory ranking; never infer prerequisites from general edges."""
        with self.driver.session() as session:
            if mode == 'chapter':
                scope = session.run("""
                    MATCH (target {name: $name})
                    WITH target, CASE apoc.meta.cypher.type(target.source_file)
                        WHEN 'LIST OF STRING' THEN target.source_file
                        WHEN 'STRING' THEN [target.source_file]
                        ELSE []
                    END AS source_files
                    RETURN target.name AS name, source_files
                    ORDER BY size(source_files) DESC
                    LIMIT 1
                """, name=target_node).single()
                if not scope:
                    return {"status": "target_not_found", "message": "目標節點不存在", "path": [], "items": []}
                source_files = list(scope.get("source_files") or [])
                coverage = self._analysis_coverage(session, mode, source_files=source_files)
                target_scope = {"mode": "chapter", "source_files": source_files}
            else:
                scope = session.run("""
                    MATCH (target {name: $name})
                    RETURN target.name AS name, target.communityId AS community
                    ORDER BY target.communityId
                    LIMIT 1
                """, name=target_node).single()
                if not scope:
                    return {"status": "target_not_found", "message": "目標節點不存在", "path": [], "items": []}
                community = scope.get("community")
                coverage = self._analysis_coverage(session, mode, community=community)
                target_scope = {"mode": "community", "community": community}

            target_scope.update(coverage)
            target_scope["analysis_state"] = self._analysis_state(coverage)

            if self._analysis_state(coverage) != "complete":
                unavailable = self._analysis_unavailable(
                    coverage,
                    "目標所在範圍的分析資料尚未完整，系統不會回傳空結果並標示成功。",
                )
                unavailable.update({"target": target_node, "target_scope": target_scope})
                return unavailable

            if mode == 'chapter':
                nodes_result = session.run("""
                    MATCH (n)
                    WHERE n.outDegree_inCommunity IS NOT NULL
                      AND n.nodeLayerInCommunity IS NOT NULL
                    WITH n, CASE apoc.meta.cypher.type(n.source_file)
                        WHEN 'LIST OF STRING' THEN n.source_file
                        WHEN 'STRING' THEN [n.source_file]
                        ELSE []
                    END AS node_files
                    WHERE any(unit IN node_files WHERE unit IN $source_files)
                    RETURN n.name AS name, head(node_files) AS community,
                           n.nodeLayerInCommunity AS layer,
                           n.outDegree_inCommunity AS outDegree
                """, source_files=source_files)
            else:
                nodes_result = session.run("""
                    MATCH (n)
                    WHERE n.communityId = $community
                      AND n.outDegree_inCommunity IS NOT NULL
                      AND n.nodeLayerInCommunity IS NOT NULL
                    RETURN n.name AS name, n.communityId AS community,
                           n.nodeLayerInCommunity AS layer,
                           n.outDegree_inCommunity AS outDegree
                """, community=community)

            learned_set = set(learned_nodes or [])
            items = [
                {
                    "name": record["name"],
                    "community": record["community"],
                    "layer": record["layer"],
                    "outDegree": record["outDegree"],
                    "learned": record["name"] in learned_set,
                }
                for record in nodes_result
            ]
            items.sort(key=lambda item: (item["layer"], -item["outDegree"], item["name"]))
            if not items:
                unavailable = self._analysis_unavailable(
                    coverage,
                    "分析覆蓋統計與查詢結果不一致；已拒絕回傳 ok 與空項目。",
                )
                unavailable.update({"target": target_node, "target_scope": target_scope})
                return unavailable

            return {
                "status": "ok",
                "analysis_state": "complete",
                "navigation_type": "exploratory_structure",
                "message": "此建議依分群、分析層級與連結性排序，不代表先備關係或固定學習路徑。",
                "target": target_node,
                "target_scope": target_scope,
                "items": items,
                "total": len(items),
                "already_reviewed": sum(1 for item in items if item["learned"]),
                "to_review": sum(1 for item in items if not item["learned"]),
                **coverage,
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
