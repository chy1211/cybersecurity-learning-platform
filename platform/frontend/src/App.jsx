import { lazy, Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route, NavLink } from 'react-router-dom'

const SkillTreePage = lazy(() => import('./pages/SkillTreePage'))
const ChatPage = lazy(() => import('./pages/ChatPage'))
const HomePage = lazy(() => import('./pages/HomePage'))
const RawGraphPage = lazy(() => import('./pages/RawGraphPage'))
const ChapterPage = lazy(() => import('./pages/ChapterPage'))
const TopicPage = lazy(() => import('./pages/TopicPage'))

function App() {
  const navLinkClass = ({ isActive }) =>
    `flex items-center px-4 transition-colors ${isActive ? 'text-indigo-400 font-semibold border-b-2 border-indigo-400' : 'text-slate-300 hover:bg-slate-800 hover:text-white border-b-2 border-transparent'}`

  return (
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div className="h-screen overflow-hidden bg-slate-950 text-slate-200 flex flex-col">
        <nav className="shrink-0 z-[100] bg-slate-900 border-b border-slate-800 shadow-lg">
          <div className="max-w-7xl mx-auto px-4">
            <div className="flex justify-between h-16">
              <div className="flex">
                <NavLink to="/" end className={navLinkClass}>
                  🛡️ <span className="ml-1 text-xl font-bold">資安學習平台</span>
                </NavLink>
                <NavLink to="/chapters" className={navLinkClass}>
                  章節導覽
                </NavLink>
                <NavLink to="/topics" className={navLinkClass}>
                  主題模組
                </NavLink>
                <NavLink to="/skill-tree" className={navLinkClass}>
                  結構導覽
                </NavLink>
                <NavLink to="/chat" className={navLinkClass}>
                  智慧導師
                </NavLink>
                <NavLink to="/raw-graph" className={navLinkClass}>
                  全知識圖譜
                </NavLink>
              </div>
            </div>
          </div>
        </nav>

        <main className="flex-1 min-h-0">
          <Suspense fallback={<div className="h-full flex items-center justify-center text-slate-400">載入頁面中…</div>}>
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/chapters" element={<ChapterPage />} />
              <Route path="/topics" element={<TopicPage />} />
              <Route path="/skill-tree" element={<SkillTreePage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/raw-graph" element={<RawGraphPage />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </Router>
  )
}

export default App
