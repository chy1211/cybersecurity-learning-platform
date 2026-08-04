import ChatComponent from '../components/ChatComponent'

export default function ChatPage() {
  return (
    <div className="max-w-[95%] mx-auto px-4 py-4 h-full overflow-hidden flex flex-col">
      <div className="bg-slate-800 rounded-lg shadow-lg border border-slate-700 flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="p-4 border-b border-slate-700 shrink-0">
          <h1 className="text-2xl font-bold text-white">AI 智慧導師</h1>
          <p className="text-slate-400">以平台展示版一跳圖譜脈絡輔助回答的智慧問答</p>
        </div>
        <ChatComponent />
      </div>
    </div>
  )
}
