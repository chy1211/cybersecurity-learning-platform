import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import { buildOverviewDescription } from '../utils/overviewText'

export default function HomePage() {
  const [stats, setStats] = useState({
    nodeCount: null,
    edgeCount: null,
    communityCount: null,
    chapterCount: null
  })

  useEffect(() => {
    let isMounted = true
    const toCount = (value) => {
      if (value === null || value === undefined) {
        return null
      }
      const parsed = Number(value)
      return Number.isFinite(parsed) ? parsed : null
    }

    api.getOverviewStats()
      .then((data) => {
        if (!isMounted) {
          return
        }
        setStats({
          nodeCount: toCount(data.node_count),
          edgeCount: toCount(data.edge_count),
          communityCount: toCount(data.community_count),
          chapterCount: toCount(data.chapter_count)
        })
      })
      .catch((error) => {
        console.error('Failed to load overview stats', error)
      })

    return () => {
      isMounted = false
    }
  }, [])

  const formatStat = (value) => (value === null ? '--' : value.toLocaleString('en-US'))

  return (
    <div className="h-full overflow-hidden flex flex-col">
      <div className="flex-1 overflow-y-auto px-4 py-12 custom-scrollbar">
        <div className="max-w-7xl mx-auto text-center">
        <h1 className="text-5xl font-bold text-white mb-4">
          歡迎來到資安職能學習平台
        </h1>
        <p className="text-xl text-slate-400 mb-4">
          結合知識圖譜與 AI 的適性化學習體驗
        </p>
        <p className="text-sm text-slate-500 max-w-2xl mx-auto mb-12">
          {buildOverviewDescription(stats)}
        </p>

        {/* Quick Stats */}
        <div className="flex justify-center gap-8 mb-12">
          <div className="text-center">
            <div className="text-3xl font-bold text-indigo-400">{formatStat(stats.nodeCount)}</div>
            <div className="text-xs text-slate-500 mt-1">知識節點</div>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-fuchsia-400">{formatStat(stats.edgeCount)}</div>
            <div className="text-xs text-slate-500 mt-1">知識關聯</div>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-emerald-400">{formatStat(stats.communityCount)}</div>
            <div className="text-xs text-slate-500 mt-1">學習社群</div>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-amber-400">{formatStat(stats.chapterCount)}</div>
            <div className="text-xs text-slate-500 mt-1">章節模組</div>
          </div>
        </div>
        
        {/* Feature Cards */}
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Link to="/chapters" className="bg-slate-800/60 border border-slate-700 p-6 rounded-xl shadow-lg hover:shadow-indigo-500/10 hover:border-indigo-500/50 hover:scale-[1.03] transition-all duration-300 cursor-pointer block group">
            <div className="text-3xl mb-3 group-hover:scale-110 transition-transform duration-300">📖</div>
            <h2 className="text-lg font-bold mb-2 text-white group-hover:text-indigo-400 transition-colors">章節導覽</h2>
            <p className="text-sm text-slate-400 group-hover:text-slate-300 transition-colors">
              依章節分類的知識圖譜，瀏覽各章節包含的知識節點與關聯
            </p>
          </Link>

          <Link to="/topics" className="bg-slate-800/60 border border-slate-700 p-6 rounded-xl shadow-lg hover:shadow-fuchsia-500/10 hover:border-fuchsia-500/50 hover:scale-[1.03] transition-all duration-300 cursor-pointer block group">
            <div className="text-3xl mb-3 group-hover:scale-110 transition-transform duration-300">🧠</div>
            <h2 className="text-lg font-bold mb-2 text-white group-hover:text-fuchsia-400 transition-colors">主題模組</h2>
            <p className="text-sm text-slate-400 group-hover:text-slate-300 transition-colors">
              基於社群偵測自動分類的主題模組，探索知識的關聯性
            </p>
          </Link>
          
          <Link to="/skill-tree" className="bg-slate-800/60 border border-slate-700 p-6 rounded-xl shadow-lg hover:shadow-emerald-500/10 hover:border-emerald-500/50 hover:scale-[1.03] transition-all duration-300 cursor-pointer block group">
            <div className="text-3xl mb-3 group-hover:scale-110 transition-transform duration-300">🗺️</div>
            <h2 className="text-lg font-bold mb-2 text-white group-hover:text-emerald-400 transition-colors">學習路徑</h2>
            <p className="text-sm text-slate-400 group-hover:text-slate-300 transition-colors">
              以拓撲分層排序的學習路徑，清楚了解先備知識與進階順序
            </p>
          </Link>
          
          <Link to="/chat" className="bg-slate-800/60 border border-slate-700 p-6 rounded-xl shadow-lg hover:shadow-amber-500/10 hover:border-amber-500/50 hover:scale-[1.03] transition-all duration-300 cursor-pointer block group">
            <div className="text-3xl mb-3 group-hover:scale-110 transition-transform duration-300">🤖</div>
            <h2 className="text-lg font-bold mb-2 text-white group-hover:text-amber-400 transition-colors">智慧導師</h2>
            <p className="text-sm text-slate-400 group-hover:text-slate-300 transition-colors">
              基於 Graph RAG 的 AI 導師，結合知識圖譜提供深度解答
            </p>
          </Link>
        </div>

        {/* Quick Start CTA */}
        <div className="mt-12 p-6 bg-gradient-to-r from-indigo-950/40 to-fuchsia-950/40 rounded-xl border border-indigo-800/30">
          <h3 className="text-lg font-bold text-white mb-2">🚀 快速開始學習</h3>
          <p className="text-sm text-slate-400 mb-4">
            前往學習路徑頁面，系統已依照拓撲分層為你排好最佳學習順序。從基礎社群開始，逐步掌握資安核心知識。
          </p>
          <Link to="/skill-tree" className="inline-block px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-lg transition-colors shadow-lg shadow-indigo-500/20">
            開始學習 →
          </Link>
        </div>
        </div>
      </div>
    </div>
  )
}
