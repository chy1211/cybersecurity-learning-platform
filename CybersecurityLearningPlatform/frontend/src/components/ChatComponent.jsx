import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import api from '../services/api'

export default function ChatComponent() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [mistakes, setMistakes] = useState([])
  const [showMistakes, setShowMistakes] = useState(true)

  useEffect(() => {
    loadMistakes()
  }, [])

  const loadMistakes = async () => {
    try {
      const data = await api.getMistakes()
      setMistakes(data)
    } catch (error) {
      console.error('Failed to load mistakes:', error)
    }
  }

  const sendMessage = async () => {
    if (!input.trim()) return

    const userMessage = { role: 'user', content: input }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const response = await api.sendChatMessage(input)
      const aiMessage = { role: 'assistant', content: response.answer }
      setMessages(prev => [...prev, aiMessage])
    } catch (error) {
      console.error('發送訊息失敗:', error)
      const errorMessage = { role: 'assistant', content: '抱歉，發生錯誤。請稍後再試。' }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  const handleExplainMistake = async (mistake) => {
    const userMessage = { 
      role: 'user', 
      content: `請解釋這題我為什麼錯了：\n題目：${mistake.question}\n我的答案：${mistake.options[mistake.user_answer_index]}\n正確答案：${mistake.options[mistake.correct_answer_index]}` 
    }
    setMessages(prev => [...prev, userMessage])
    setLoading(true)

    try {
      const response = await api.explainMistake(mistake.id)
      const aiMessage = { role: 'assistant', content: response.explanation }
      setMessages(prev => [...prev, aiMessage])
    } catch (error) {
      console.error('Explanation failed:', error)
      const errorMessage = { role: 'assistant', content: '抱歉，無法取得解釋。' }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-1 min-h-0 gap-0 p-4 overflow-hidden">
      {/* Mistakes Sidebar */}
      <div className={`w-1/4 bg-slate-900 border border-slate-700 rounded-lg flex flex-col min-h-0 ${showMistakes ? '' : 'hidden'}`}>
        <div className="p-4 border-b border-slate-700 bg-red-900/20 rounded-t-lg flex justify-between items-center shrink-0">
          <h3 className="font-bold text-red-400">錯題本 ({mistakes.length})</h3>
          <button onClick={loadMistakes} className="text-sm text-indigo-400 hover:underline">重新整理</button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {mistakes.length === 0 ? (
            <p className="text-slate-500 text-center mt-10">目前沒有錯題紀錄</p>
          ) : (
            mistakes.map((mistake) => (
              <div 
                key={mistake.id} 
                onClick={() => handleExplainMistake(mistake)}
                className="p-3 border border-slate-700 rounded hover:bg-slate-800 cursor-pointer transition-colors text-left group"
              >
                <p className="font-medium text-sm line-clamp-2 mb-1 text-slate-300 group-hover:text-indigo-400">
                  {mistake.question || <span className="text-slate-500 italic">題目資料遺失</span>}
                </p>
                <div className="text-xs text-slate-500 flex justify-between">
                  <span>{new Date(mistake.timestamp).toLocaleDateString()}</span>
                  <span className="text-red-400">點擊解釋</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col bg-slate-900 border border-slate-700 rounded-lg min-h-0 ml-4">
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-slate-500 mt-20">
              <p className="text-lg">👋 您好！我是資安智慧導師</p>
              <p className="text-sm mt-2">問我任何資安相關問題，或點擊左側錯題尋求解釋！</p>
            </div>
          )}
          
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-lg p-4 ${
                msg.role === 'user' 
                  ? 'bg-indigo-600 text-white' 
                  : 'bg-slate-800 text-slate-200'
              }`}>
                {msg.role === 'assistant' ? (
                  <ReactMarkdown className="prose prose-sm prose-invert max-w-none">{msg.content}</ReactMarkdown>
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-800 rounded-lg p-4">
                <div className="flex space-x-2">
                  <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{animationDelay: '0.1s'}}></div>
                  <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{animationDelay: '0.2s'}}></div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-slate-700 p-5 shrink-0">
          <div className="flex space-x-3">
            <button 
              onClick={() => setShowMistakes(!showMistakes)}
              className="px-3 py-2 border border-slate-600 rounded-lg hover:bg-slate-800 text-slate-400"
              title={showMistakes ? "隱藏錯題本" : "顯示錯題本"}
            >
              {showMistakes ? '📖' : '📕'}
            </button>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
              placeholder="輸入您的問題..."
              className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              disabled={loading}
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="bg-indigo-600 text-white px-6 py-2 rounded-lg hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              發送
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
