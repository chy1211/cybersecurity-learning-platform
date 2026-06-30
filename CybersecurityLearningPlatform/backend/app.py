from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import datetime
import uuid
from config import Config
from neo4j_service import Neo4jService
from llm_service import LLMService
import persistence_service

app = Flask(__name__)
CORS(app)

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

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "mode": "neo4j"})

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_query = data.get('message', '')
        if not user_query:
            return jsonify({"error": "訊息不能為空"}), 400
        
        log_file = create_log_file('chat')
        
        entities = db_service.search_entities(user_query)
        if not entities:
            entities = llm_service.identify_entities_in_query(user_query, log_file=log_file)
        
        context = None
        if entities:
            context = db_service.get_entity_context(entities[0])
        
        if context:
            answer = llm_service.generate_answer_with_context(user_query, context, log_file=log_file)
        else:
            answer = "抱歉，我在知識庫中沒有找到相關資訊。請問您能更具體地描述您的問題嗎？"
        
        return jsonify({"answer": answer, "context_entity": entities[0] if entities else None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/skill-tree', methods=['GET'])
def get_skill_tree():
    try:
        return jsonify(db_service.get_skill_tree_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/knowledge-graph/raw', methods=['GET'])
def get_raw_knowledge_graph():
    try:
        return jsonify(db_service.get_raw_knowledge_graph())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/overview-stats', methods=['GET'])
def get_overview_stats():
    try:
        return jsonify(db_service.get_overview_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/mistakes', methods=['GET'])
def get_mistakes():
    try:
        mistakes = persistence_service.load_mistakes()
        return jsonify(mistakes)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/mistakes/record', methods=['POST'])
def record_mistake():
    try:
        data = request.get_json()
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
        persistence_service.save_mistakes(mistakes)
        
        return jsonify({"success": True, "mistake": mistake})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/mistakes/explain', methods=['POST'])
def explain_mistake():
    try:
        data = request.get_json()
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
        return jsonify({"error": str(e)}), 500


@app.route('/api/quiz/generate', methods=['POST'])
def generate_quiz():
    try:
        data = request.get_json()
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
        return jsonify({"error": str(e)}), 500

# Placement test endpoints are currently deprecated due to Neo4j migration.
@app.route('/api/placement-test', methods=['GET'])
def get_placement_test():
    return jsonify([])

@app.route('/api/placement-test/submit', methods=['POST'])
def submit_placement_test():
    return jsonify({"unlocked_nodes": [], "correct_count": 0, "total_count": 0})

@app.route('/api/node/<node_id>/neighbors', methods=['GET'])
def get_node_neighbors(node_id):
    try:
        limit = int(request.args.get('limit', 20))
        relations = db_service.get_node_neighbors(node_id, limit=limit)
        return jsonify({"relations": relations})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/node/complete', methods=['POST'])
def complete_node():
    return jsonify({"success": True, "unlocked_nodes": []})

@app.route('/api/chapters', methods=['GET'])
def get_chapters():
    try:
        return jsonify(db_service.get_all_chapters())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/chapters/<unit>/graph', methods=['GET'])
def get_chapter_graph(unit):
    try:
        limit_arg = request.args.get('limit')
        limit = int(limit_arg) if limit_arg not in (None, '') else None
        return jsonify(db_service.get_chapter_graph(unit, limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/communities', methods=['GET'])
def get_communities():
    try:
        return jsonify(db_service.get_all_communities())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/communities/<community>/graph', methods=['GET'])
def get_community_graph(community):
    try:
        limit_arg = request.args.get('limit')
        limit = int(limit_arg) if limit_arg not in (None, '') else None
        return jsonify(db_service.get_community_graph(community, limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning-paths/communities', methods=['GET'])
def get_community_learning_paths():
    try:
        return jsonify(db_service.get_community_learning_paths())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/learning-paths/chapters', methods=['GET'])
def get_chapter_learning_paths():
    try:
        return jsonify(db_service.get_chapter_learning_paths())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/learning-paths/plan', methods=['POST'])
def plan_learning_path():
    try:
        data = request.get_json()
        target_node = data.get('target_node')
        learned_nodes = data.get('learned_nodes', [])
        mode = data.get('mode', 'community')
        if not target_node:
            return jsonify({"error": "Missing target_node"}), 400
        result = db_service.plan_learning_path(target_node, learned_nodes, mode)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/learning-paths/search', methods=['GET'])
def search_nodes():
    try:
        query = request.args.get('q', '')
        mode = request.args.get('mode', 'community')
        if len(query) < 1:
            return jsonify([])
        return jsonify(db_service.search_nodes_by_name(query, mode=mode))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/user-progress', methods=['GET'])
def get_user_progress():
    try:
        progress = persistence_service.load_progress()
        return jsonify({"learned_nodes": progress})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/user-progress/toggle', methods=['POST'])
def toggle_user_progress():
    try:
        data = request.get_json()
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
        persistence_service.save_progress(progress)
        return jsonify({"success": True, "action": action, "learned_nodes": progress})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG, use_reloader=False)
