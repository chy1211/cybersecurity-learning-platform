import axios from 'axios'

const API_BASE = '/api'

const api = {
  async getSkillTree() {
    const response = await axios.get(`${API_BASE}/skill-tree`)
    return response.data
  },


  async getRawKnowledgeGraph() {
    const response = await axios.get(`${API_BASE}/knowledge-graph/raw`)
    return response.data
  },

  async getOverviewStats() {
    const response = await axios.get(`${API_BASE}/overview-stats`)
    return response.data
  },

  async getChapters() {
    const response = await axios.get(`${API_BASE}/chapters`)
    return response.data
  },

  async getChapterGraph(chapter) {
    const response = await axios.get(`${API_BASE}/chapters/${encodeURIComponent(chapter)}/graph`)
    return response.data
  },

  async getCommunities() {
    const response = await axios.get(`${API_BASE}/communities`)
    return response.data
  },

  async getCommunityGraph(community) {
    const response = await axios.get(`${API_BASE}/communities/${encodeURIComponent(community)}/graph`)
    return response.data
  },

  async sendChatMessage(message) {
    const response = await axios.post(`${API_BASE}/chat`, { message })
    return response.data
  },


  async getHealth() {
    const response = await axios.get(`${API_BASE}/health`)
    return response.data
  },

  async getPlacementTest() {
    const response = await axios.get(`${API_BASE}/placement-test`)
    return response.data
  },

  async submitPlacementTest(answers, testId) {
    const response = await axios.post(`${API_BASE}/placement-test/submit`, { answers, test_id: testId })
    return response.data
  },

  async completeNode(nodeId) {
    const response = await axios.post(`${API_BASE}/node/complete`, { node_id: nodeId })
    return response.data
  },

  async getNodeNeighbors(nodeId, limit = 20) {
    const response = await axios.get(`${API_BASE}/node/${encodeURIComponent(nodeId)}/neighbors?limit=${limit}`)
    return response.data
  },

  async generateQuiz(nodeId) {
    const response = await axios.post(`${API_BASE}/quiz/generate`, { node_id: nodeId })
    return response.data
  },

  async getMistakes() {
    const response = await axios.get(`${API_BASE}/mistakes`)
    return response.data
  },

  async recordMistake(data) {
    const response = await axios.post(`${API_BASE}/mistakes/record`, data)
    return response.data
  },

  async explainMistake(mistakeId) {
    const response = await axios.post(`${API_BASE}/mistakes/explain`, { mistake_id: mistakeId })
    return response.data
  },

  async getCommunityLearningPaths() {
    const response = await axios.get(`${API_BASE}/learning-paths/communities`)
    return response.data
  },

  async getChapterLearningPaths() {
    const response = await axios.get(`${API_BASE}/learning-paths/chapters`)
    return response.data
  },

  async planLearningPath(targetNode, learnedNodes, mode = 'community') {
    const response = await axios.post(`${API_BASE}/learning-paths/plan`, {
      target_node: targetNode,
      learned_nodes: learnedNodes,
      mode
    })
    return response.data
  },

  async searchNodes(query, mode = 'community') {
    const response = await axios.get(`${API_BASE}/learning-paths/search?q=${encodeURIComponent(query)}&mode=${encodeURIComponent(mode)}`)
    return response.data
  },

  async getUserProgress() {
    const response = await axios.get(`${API_BASE}/user-progress`)
    return response.data
  },

  async toggleUserProgress(nodeId) {
    const response = await axios.post(`${API_BASE}/user-progress/toggle`, { node_id: nodeId })
    return response.data
  }
}

export default api
