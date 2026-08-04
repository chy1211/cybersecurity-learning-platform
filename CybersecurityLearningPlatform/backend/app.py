from flask import Flask, request, jsonify, g
from flask_cors import CORS
import os
import json
import datetime
import uuid
import logging
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from config import Config
from neo4j_service import Neo4jService
from llm_service import LLMService
import persistence_service

app = Flask(__name__)
CORS(app, origins=Config.CORS_ORIGINS)
logging.basicConfig(level=logging.INFO)

_rate_hits = defaultdict(deque)
_rate_lock = threading.Lock()


@app.before_request
def assign_request_id():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())


def _internal_error(exc):
    app.logger.error("request_failed request_id=%s", g.request_id, exc_info=True)
    return jsonify({
        "error": "internal_service_error",
        "message": "服務暫時無法完成請求。",
        "request_id": g.request_id,
    }), 500


def rate_limited(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        now = time.monotonic()
        key = (request.endpoint, request.remote_addr or "local")
        with _rate_lock:
            hits = _rate_hits[key]
            cutoff = now - Config.RATE_LIMIT_WINDOW_SECONDS
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= Config.RATE_LIMIT_REQUESTS:
                return jsonify({
                    "error": "rate_limit_exceeded",
                    "message": "請稍後再試。",
                    "request_id": g.request_id,
                }), 429
            hits.append(now)
        return view(*args, **kwargs)
    return wrapped

# Ensure logs directory exists
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

def create_log_file(endpoint_name):
    """Create a unique log file path for the current request"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}_{endpoint_name}.txt"
    return os.path.join(LOG_DIR, filename)

print("使用 Neo4j 資料庫模式")
db_service = Neo4jService()
llm_service = LLMService()

@app.route('/api/health/live', methods=['GET'])
def health_live():
    return jsonify({"status": "live"})


@app.route('/api/health/ready', methods=['GET'])
def health_ready():
    ready, reason = db_service.check_readiness()
    if not ready:
        return jsonify({"status": "not_ready", "reason": reason}), 503
    return jsonify({"status": "ready", "neo4j": "connected"})

@app.route('/api/chat', methods=['POST'])
@rate_limited
def chat():
    try:
        data = request.get_json(silent=True) or {}
        user_query = data.get('message', '')
        if not user_query:
            return jsonify({"error": "訊息不能為空"}), 400
        
        log_file = create_log_file('chat')
        
        graph_context = db_service.get_graph_rag_subgraph(user_query)

        if graph_context and graph_context.get("edges"):
            answer = llm_service.generate_answer_with_context(user_query, graph_context, log_file=log_file)
        else:
            answer = "抱歉，我在知識庫中沒有找到相關資訊。請問您能更具體地描述您的問題嗎？"

        seeds = graph_context.get("seeds", []) if graph_context else []
        edges = graph_context.get("edges", []) if graph_context else []
        # evidence 直接由送進模型的邊轉出，確保「顯示的依據」＝「模型看到的內容」
        evidence = [
            {
                "entity": edge["source"],
                "relationship": edge["relation"],
                "neighbor": edge["target"],
                "source": edge.get("source_files", []),
            }
            for edge in edges
        ]

        return jsonify({
            "answer": answer,
            "context_entity": seeds[0]["name"] if seeds else None,
            "candidate": seeds[0] if seeds else None,
            "evidence": evidence,
            "graph_context": graph_context,
            "retrieval_mode": graph_context["retrieval"]["mode"] if graph_context else None,
        })
    except Exception as e:
        return _internal_error(e)

@app.route('/api/knowledge-graph/raw', methods=['GET'])
def get_raw_knowledge_graph():
    try:
        return jsonify(db_service.get_raw_knowledge_graph())
    except Exception as e:
        return _internal_error(e)

@app.route('/api/overview-stats', methods=['GET'])
def get_overview_stats():
    try:
        return jsonify(db_service.get_overview_stats())
    except Exception as e:
        return _internal_error(e)

@app.route('/api/mistakes', methods=['GET'])
def get_mistakes():
    try:
        mistakes = persistence_service.load_mistakes()
        return jsonify(mistakes)
    except Exception as e:
        return _internal_error(e)

@app.route('/api/mistakes/record', methods=['POST'])
def record_mistake():
    try:
        data = request.get_json(silent=True) or {}
        question_data = data.get('question_data')
        user_answer_index = data.get('user_answer_index')
        
        if not question_data or user_answer_index is None:
            return jsonify({"error": "Missing data"}), 400
            
        mistakes = persistence_service.load_mistakes()
        mistake = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.datetime.now().isoformat(),
            "question": question_data.get("question"),
            "options": question_data.get("options"),
            "user_answer_index": user_answer_index,
            "correct_answer_index": question_data.get("correctAnswer"),
            "entity_name": question_data.get("entity_name"),
            "explanation": question_data.get("explanation", ""),
            "node_id": question_data.get("node_id", "")
        }
        mistakes.append(mistake)
        if not persistence_service.save_mistakes(mistakes):
            raise RuntimeError("mistake_persistence_failed")
        
        return jsonify({"success": True, "mistake": mistake})
    except Exception as e:
        return _internal_error(e)

@app.route('/api/mistakes/explain', methods=['POST'])
@rate_limited
def explain_mistake():
    try:
        data = request.get_json(silent=True) or {}
        mistake_id = data.get('mistake_id')
        
        if not mistake_id:
            return jsonify({"error": "Missing mistake_id"}), 400
            
        mistakes = persistence_service.load_mistakes()
        mistake = next((m for m in mistakes if m['id'] == mistake_id), None)
        
        if not mistake:
            return jsonify({"error": "Mistake not found"}), 404
        
        entity_name = mistake.get('entity_name')
        context = f"關於 {entity_name} 的知識點。" if entity_name else ""
        
        log_file = create_log_file('explain_mistake')
        explanation = llm_service.explain_mistake(
            mistake['question'],
            mistake['options'][mistake['user_answer_index']],
            mistake['options'][mistake['correct_answer_index']],
            context,
            log_file=log_file
        )
        
        return jsonify({"explanation": explanation})
    except Exception as e:
        return _internal_error(e)


@app.route('/api/quiz/generate', methods=['POST'])
@rate_limited
def generate_quiz():
    try:
        data = request.get_json(silent=True) or {}
        node_id = data.get('node_id')
        
        if not node_id:
            return jsonify({"error": "Missing node_id"}), 400
            
        # The node_id corresponds to the entity name in the neo4j graph now
        entity_name = node_id
        
        # Load Knowledge Graph Context dynamically from Neo4j
        kg_context = db_service.get_entity_context(entity_name)
        if not kg_context:
            kg_context = f"請生成關於 {entity_name} 的資安測驗題。"
            
        # Generate Quiz
        log_file = create_log_file('generate_quiz')
        questions = llm_service.generate_quiz(entity_name, kg_context, log_file=log_file)
        
        return jsonify({"questions": questions})
        
    except Exception as e:
        return _internal_error(e)

@app.route('/api/node/<node_id>/neighbors', methods=['GET'])
def get_node_neighbors(node_id):
    try:
        limit = int(request.args.get('limit', 20))
        relations = db_service.get_node_neighbors(node_id, limit=limit)
        return jsonify({"relations": relations})
    except Exception as e:
        return _internal_error(e)

@app.route('/api/chapters', methods=['GET'])
def get_chapters():
    try:
        return jsonify(db_service.get_all_chapters())
    except Exception as e:
        return _internal_error(e)

@app.route('/api/chapters/<unit>/graph', methods=['GET'])
def get_chapter_graph(unit):
    try:
        limit_arg = request.args.get('limit')
        limit = int(limit_arg) if limit_arg not in (None, '') else None
        return jsonify(db_service.get_chapter_graph(unit, limit))
    except Exception as e:
        return _internal_error(e)

@app.route('/api/communities', methods=['GET'])
def get_communities():
    try:
        return jsonify(db_service.get_all_communities())
    except Exception as e:
        return _internal_error(e)

@app.route('/api/communities/<community>/graph', methods=['GET'])
def get_community_graph(community):
    try:
        limit_arg = request.args.get('limit')
        limit = int(limit_arg) if limit_arg not in (None, '') else None
        return jsonify(db_service.get_community_graph(community, limit))
    except Exception as e:
        return _internal_error(e)


@app.route('/api/learning-paths/communities', methods=['GET'])
def get_community_learning_paths():
    try:
        return jsonify(db_service.get_community_learning_paths())
    except Exception as e:
        return _internal_error(e)

@app.route('/api/learning-paths/chapters', methods=['GET'])
def get_chapter_learning_paths():
    try:
        return jsonify(db_service.get_chapter_learning_paths())
    except Exception as e:
        return _internal_error(e)

@app.route('/api/learning-paths/plan', methods=['POST'])
def plan_learning_path():
    try:
        data = request.get_json(silent=True) or {}
        target_node = data.get('target_node')
        learned_nodes = data.get('learned_nodes', [])
        mode = data.get('mode', 'community')
        if not target_node:
            return jsonify({"error": "Missing target_node"}), 400
        result = db_service.plan_learning_path(target_node, learned_nodes, mode)
        return jsonify(result)
    except Exception as e:
        return _internal_error(e)

@app.route('/api/learning-paths/search', methods=['GET'])
def search_nodes():
    try:
        query = request.args.get('q', '')
        mode = request.args.get('mode', 'community')
        if len(query) < 1:
            return jsonify([])
        return jsonify(db_service.search_nodes_by_name(query, mode=mode))
    except Exception as e:
        return _internal_error(e)

@app.route('/api/user-progress', methods=['GET'])
def get_user_progress():
    try:
        progress = persistence_service.load_progress()
        return jsonify({"learned_nodes": progress})
    except Exception as e:
        return _internal_error(e)

@app.route('/api/user-progress/toggle', methods=['POST'])
def toggle_user_progress():
    try:
        data = request.get_json(silent=True) or {}
        node_id = data.get('node_id')
        if not node_id:
            return jsonify({"error": "Missing node_id"}), 400
        progress = persistence_service.load_progress()
        if node_id in progress:
            progress.remove(node_id)
            action = "removed"
        else:
            progress.append(node_id)
            action = "added"
        if not persistence_service.save_progress(progress):
            raise RuntimeError("progress_persistence_failed")
        return jsonify({"success": True, "action": action, "learned_nodes": progress})
    except Exception as e:
        return _internal_error(e)


if __name__ == '__main__':
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG, use_reloader=False)
