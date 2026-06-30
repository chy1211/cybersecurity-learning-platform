import { useState, useEffect, useCallback, useRef, useMemo, memo } from 'react'
import { ReactFlow, Background, Controls, Handle, Position } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import dagre from 'dagre'
import api from '../services/api'
import LearningMode from '../components/LearningMode'
import { getCommunityName } from '../services/communityNames'
import { filterDisplayCommunities, filterSearchResultsByVisibleCommunities } from '../utils/communityFilters'

const NODE_W = 180;
const NODE_H = 44;

function dagreLayout(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 60, acyclicer: 'greedy', ranker: 'tight-tree' });
  nodes.forEach(n => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach(e => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map(n => { const p = g.node(n.id); return { ...n, position: { x: p.x - NODE_W/2, y: p.y - NODE_H/2 } }; });
}

/* ── Color palette for communities ─────────────── */
const COMM_COLORS = [
  '#6366f1','#8b5cf6','#a855f7','#ec4899','#f43f5e',
  '#ef4444','#f97316','#f59e0b','#eab308','#84cc16',
  '#22c55e','#14b8a6','#06b6d4','#3b82f6','#2563eb',
];
function commColor(id) { return COMM_COLORS[Math.abs(Number(id)) % COMM_COLORS.length]; }

/* ── Degree badge color ────────────────────────── */
function degreeBg(d) {
  if (d >= 10) return 'bg-amber-500/20 text-amber-300 border-amber-500/30';
  if (d >= 5)  return 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30';
  if (d >= 2)  return 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30';
  return 'bg-slate-700/40 text-slate-400 border-slate-600/30';
}

export default function SkillTreePage() {
  const pathMode = 'community'
  const [communities, setCommunities] = useState([])
  const [loading, setLoading] = useState(true)
  const [learnedNodes, setLearnedNodes] = useState(new Set())
  const [expandedComm, setExpandedComm] = useState(null)
  const [learningNode, setLearningNode] = useState(null)

  // Path planner state
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [selectedTarget, setSelectedTarget] = useState(null)
  const [plannedPath, setPlannedPath] = useState(null)
  const [planning, setPlanning] = useState(false)
  const searchTimerRef = useRef(null)

  // Load data on mount
  useEffect(() => {
    setLoading(true)
    const fetchPaths = api.getCommunityLearningPaths()
    Promise.all([
      fetchPaths,
      api.getUserProgress()
    ]).then(([paths, progress]) => {
      let nextCommunities = filterDisplayCommunities(paths)
      let initialCommunity = nextCommunities.length > 0 ? nextCommunities[0].community : null
      setCommunities(nextCommunities)
      setLearnedNodes(new Set(progress.learned_nodes || []))
      setExpandedComm(initialCommunity)
      setLoading(false)
    }).catch(err => {
      console.error(err)
      setLoading(false)
    })
  }, [])

  // Search debounce
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (searchQuery.length < 1) { setSearchResults([]); return }
    const q = searchQuery.trim().toLowerCase()
    if (q.length > 0 && communities.length > 0) {
      const localResults = []
      const seen = new Set()
      communities.forEach((comm) => {
        comm.nodes.forEach((node) => {
          if (localResults.length >= 10) return
          if (!node.name.toLowerCase().includes(q)) return
          if (seen.has(node.name)) return
          seen.add(node.name)
          localResults.push({
            name: node.name,
            community: comm.community,
            layer: node.layer ?? null
          })
        })
      })
      if (localResults.length > 0) {
        setSearchResults(localResults)
      }
    }
    searchTimerRef.current = setTimeout(() => {
      api.searchNodes(searchQuery, pathMode)
        .then((results) => setSearchResults(filterSearchResultsByVisibleCommunities(results, communities)))
        .catch(console.error)
    }, 300)
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current) }
  }, [searchQuery, pathMode, communities])

  const toggleLearned = useCallback((nodeId) => {
    api.toggleUserProgress(nodeId).then(res => {
      setLearnedNodes(new Set(res.learned_nodes || []))
    }).catch(console.error)
  }, [])

  const handlePlan = useCallback(() => {
    if (!selectedTarget) return
    setPlanning(true)
    api.planLearningPath(selectedTarget.name, Array.from(learnedNodes), pathMode)
      .then(res => { setPlannedPath(res); setPlanning(false) })
      .catch(err => { console.error(err); setPlanning(false) })
  }, [selectedTarget, learnedNodes, pathMode])

  const handleStartLearning = useCallback((nodeName) => {
    setLearningNode({ id: nodeName, data: { label: nodeName, status: 'unlocked' } })
  }, [])

  const handleLearningComplete = useCallback(() => {
    if (learningNode) {
      toggleLearned(learningNode.id)
    }
    setLearningNode(null)
  }, [learningNode, toggleLearned])

  useEffect(() => {
    if (!selectedTarget) return
    const match = communities.find(c => String(c.community) === String(selectedTarget.community))
    if (match) setExpandedComm(match.community)
  }, [selectedTarget, communities])

  // Computed: community search filter
  const [commFilter, setCommFilter] = useState('')
  const filteredComms = useMemo(() => {
    if (!commFilter) return communities
    const q = commFilter.toLowerCase()
    return communities.filter(c => {
      if (String(c.community).includes(q)) return true
      return c.nodes.some(n => n.name.toLowerCase().includes(q))
    })
  }, [communities, commFilter])

  if (learningNode) {
    return <LearningMode chapter={learningNode} onClose={() => setLearningNode(null)} onComplete={handleLearningComplete} />
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500 mx-auto mb-4"></div>
          <p className="text-slate-400">載入學習路徑資料...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-hidden bg-slate-950 flex flex-col">
      {/* Header */}
      <div className="shrink-0 z-[90] bg-slate-900/95 backdrop-blur-sm border-b border-slate-800">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <span>🗺️</span> 學習路徑導覽
            
            <span className="ml-4 text-xs font-medium text-indigo-300 bg-indigo-900/30 border border-indigo-800/60 px-2 py-0.5 rounded">🌐 主題模組學習</span>
          </h1>
          
          <div className="text-xs text-slate-500">
            已學會 <span className="text-emerald-400 font-bold">{learnedNodes.size}</span> 個知識點
          </div>
        </div>
      </div>

      {/* Two-column content */}
      <div className="flex-1 overflow-hidden">
        <div className="h-full flex flex-col lg:flex-row">
          <div className="flex-1 min-h-0 border-b lg:border-b-0 lg:border-r border-slate-800">
            <CommunityPathsView
              communities={filteredComms}
              learnedNodes={learnedNodes}
              expandedComm={expandedComm}
              setExpandedComm={setExpandedComm}
              selectedTarget={selectedTarget}
              toggleLearned={toggleLearned}
              onStartLearning={handleStartLearning}
              commFilter={commFilter}
              setCommFilter={setCommFilter}
              totalComms={communities.length}
              pathMode={pathMode}
            />
          </div>
          <div className="flex-1 min-h-0 lg:w-[380px] lg:flex-none">
            <PathPlannerView
              searchQuery={searchQuery}
              setSearchQuery={setSearchQuery}
              setSearchResults={setSearchResults}
              searchResults={searchResults}
              selectedTarget={selectedTarget}
              setSelectedTarget={setSelectedTarget}
              plannedPath={plannedPath}
              planning={planning}
              handlePlan={handlePlan}
              learnedNodes={learnedNodes}
              toggleLearned={toggleLearned}
              onStartLearning={handleStartLearning}
              pathMode={pathMode}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════
   Tab 1: Community Paths View
   ══════════════════════════════════════════════════ */
function CommunityPathsView({ communities, learnedNodes, expandedComm, setExpandedComm, selectedTarget, toggleLearned, onStartLearning, commFilter, setCommFilter, totalComms, pathMode }) {
  const [layoutMode, setLayoutMode] = useState('list') // 'graph' | 'list'
  const commRefs = useRef({})

  useEffect(() => {
    if (expandedComm == null) return
    const targetEl = commRefs.current[expandedComm]
    if (targetEl && typeof targetEl.scrollIntoView === 'function') {
      targetEl.scrollIntoView({ block: 'nearest' })
    }
  }, [expandedComm, communities])
  return (
    <div className="flex flex-1 min-h-0 h-full">
      {/* Left: Community List */}
      <div className="w-80 border-r border-slate-800 overflow-y-auto bg-slate-900/50 shrink-0">
        <div className="p-3 border-b border-slate-800 sticky top-0 bg-slate-900/95 backdrop-blur-sm z-10">
          <input
            type="text"
            placeholder={pathMode === 'community' ? "搜尋主題或節點..." : "搜尋章節或節點..."}
            value={commFilter}
            onChange={e => setCommFilter(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <p className="text-xs text-slate-500 mt-2">
            共 {totalComms} 個{pathMode === 'community' ? '主題' : '章節'} · 依學習先後順序排列
          </p>
          {/* Layout toggle */}
          <div className="flex gap-1 mt-2 bg-slate-800 rounded-lg p-0.5">
            <button onClick={() => setLayoutMode('list')} className={`flex-1 px-2 py-1 rounded text-xs font-medium transition-all ${layoutMode === 'list' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}>📋 列表</button>
            <button onClick={() => setLayoutMode('graph')} className={`flex-1 px-2 py-1 rounded text-xs font-medium transition-all ${layoutMode === 'graph' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}>🔀 DAG</button>
          </div>
        </div>
        <div className="divide-y divide-slate-800/50">
          {communities.map((comm, idx) => {
            const learnedCount = comm.nodes.filter(n => learnedNodes.has(n.name)).length
            const isActive = expandedComm === comm.community
            return (
              <button
                key={comm.community}
                ref={el => { if (el) commRefs.current[comm.community] = el }}
                onClick={() => setExpandedComm(isActive ? null : comm.community)}
                className={`w-full text-left p-3 transition-all group ${isActive ? 'bg-indigo-950/40 border-l-2 border-indigo-500' : 'hover:bg-slate-800/50 border-l-2 border-transparent'}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-5 h-5 rounded-full shrink-0 flex items-center justify-center text-[9px] font-bold text-white/80" style={{ background: commColor(comm.community) }}>{idx + 1}</span>
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="text-sm font-bold text-white truncate">
                      {pathMode === 'community' ? getCommunityName(comm.community) : comm.community}
                    </span>
                    <span className="text-[10px] text-slate-600">#{comm.community}</span>
                  </div>
                  <span className="ml-auto text-xs text-slate-500 shrink-0">{comm.size} 節點</span>
                </div>
                <div className="flex items-center gap-2 ml-6">
                  <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 transition-all" style={{ width: `${comm.size > 0 ? (learnedCount / comm.size) * 100 : 0}%` }}></div>
                  </div>
                  <span className="text-xs text-slate-500 shrink-0">{learnedCount}/{comm.size}</span>
                </div>
                {comm.interOutDegree > 0 && (
                  <p className="text-[10px] text-slate-600 ml-6 mt-1">
                    跨{pathMode === 'community' ? '主題' : '章節'}基礎度: {comm.interOutDegree}
                  </p>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Right: Community Detail */}
      <div className="flex-1 overflow-y-auto">
        {expandedComm !== null ? (
          layoutMode === 'graph' ? (
            <CommunityDetailGraph
              community={communities.find(c => c.community === expandedComm)}
              learnedNodes={learnedNodes}
              toggleLearned={toggleLearned}
              onStartLearning={onStartLearning}
              pathMode={pathMode}
              selectedTarget={selectedTarget}
            />
          ) : (
            <CommunityDetailList
              community={communities.find(c => c.community === expandedComm)}
              learnedNodes={learnedNodes}
              toggleLearned={toggleLearned}
              onStartLearning={onStartLearning}
              pathMode={pathMode}
              selectedTarget={selectedTarget}
            />
          )
        ) : (
          <div className="flex items-center justify-center h-full text-slate-600">
            <div className="text-center">
              <p className="text-5xl mb-4">📖</p>
              <p className="text-lg font-medium">選擇左側社群以查看學習順序</p>
              <p className="text-sm mt-2">Out-Degree 越高的節點越基礎，應優先學習</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Custom Node for dagre graph ───────────────── */
function CommNodeInner({ data }) {
  const learned = data.learned;
  const isTarget = data.isTarget;
  const bg = learned ? '#059669' : '#6366f1';
  const border = isTarget ? '#f59e0b' : (data._selected ? '#ffffff' : (learned ? '#34d399' : '#818cf8'));
  const glow = isTarget ? `0 0 14px ${border}` : (data._selected ? `0 0 12px ${bg}` : 'none');
  return (
    <div style={{ width: NODE_W, height: NODE_H, background: bg, border: `2px solid ${border}`, borderRadius: 22, display: 'flex', alignItems: 'center', gap: 6, padding: '0 12px', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer', transition: 'all .2s', boxShadow: glow }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <span style={{ flexShrink: 0, fontSize: 10 }}>{learned ? '✓' : `OD:${data.outDegree}`}</span>
      {isTarget && <span style={{ flexShrink: 0 }}>★</span>}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{data.label}</span>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}
const CommNode = memo(CommNodeInner);
const commNodeTypes = { commNode: CommNode };

/* ── Community Detail: Dagre Graph Mode ───────── */
function CommunityDetailGraph({ community, learnedNodes, toggleLearned, onStartLearning, pathMode, selectedTarget }) {
  if (!community) return null;
  const [selectedName, setSelectedName] = useState(null);

  const { flowNodes, flowEdges } = useMemo(() => {
    const rawNodes = (community?.nodes || []).map(n => ({
      id: n.name, type: 'commNode',
      position: { x: 0, y: 0 },
      data: { label: n.name, learned: learnedNodes.has(n.name), outDegree: n.outDegree ?? 0, _selected: false, isTarget: selectedTarget?.name === n.name }
    }));
    
    const nodeNames = new Set(rawNodes.map(n => n.id));
    const rawEdges = (community?.edges || [])
      .filter(e => nodeNames.has(e.source) && nodeNames.has(e.target))
      .map((e, i) => ({
        id: `ce-${i}`, source: e.source, target: e.target,
        style: { stroke: '#475569', strokeWidth: 1.5 },
        markerEnd: { type: 'arrowclosed', color: '#475569', width: 12, height: 12 },
      }));
      
    const laid = dagreLayout(rawNodes, rawEdges);
    return { flowNodes: laid, flowEdges: rawEdges };
  }, [community, learnedNodes, selectedTarget]);

  const learnedCount = community.nodes.filter(n => learnedNodes.has(n.name)).length;
  const pct = community.size > 0 ? Math.round((learnedCount / community.size) * 100) : 0;
  const sel = community.nodes.find(n => n.name === selectedName);

  return (
    <div className="flex flex-col h-full">
      <CommunityHeader community={community} pct={pct} learnedCount={learnedCount} hint="箭頭方向代表知識依賴：從上到下為先備到進階。點擊節點可操作。" pathMode={pathMode} />
      <div className="flex-1 relative" style={{ minHeight: 400 }}>
        <ReactFlow
          nodes={flowNodes} edges={flowEdges} nodeTypes={commNodeTypes}
          fitView fitViewOptions={{ padding: 0.15 }}
          minZoom={0.2} maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
          style={{ background: 'transparent' }}
          defaultEdgeOptions={{ type: 'smoothstep' }}
          nodesDraggable={false} nodesConnectable={false}
          onNodeClick={(_, node) => setSelectedName(node.id)}
        >
          <Background color="#1e293b" gap={24} size={1} />
          <Controls position="bottom-left" style={{ background: '#1e293b', borderColor: '#334155', borderRadius: 8 }} />
        </ReactFlow>
      </div>
      {sel && (
        <div className="p-3 border-t border-slate-800 bg-slate-900/90 flex items-center gap-3 shrink-0">
          <span className="text-sm text-white font-bold truncate flex-1">{sel.name}</span>
          <span className={`px-2 py-0.5 rounded text-xs border ${degreeBg(sel.outDegree)}`}>OD:{sel.outDegree}</span>
          <button onClick={() => toggleLearned(sel.name)} className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${learnedNodes.has(sel.name) ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-700 border-slate-600 text-slate-300 hover:border-indigo-500'}`}>
            {learnedNodes.has(sel.name) ? '✓ 已學會' : '標記已學會'}
          </button>
          <button onClick={() => onStartLearning(sel.name)} className="px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white transition-all">開始學習</button>
          <button onClick={() => setSelectedName(null)} className="text-slate-500 hover:text-white text-sm">✕</button>
        </div>
      )}
    </div>
  );
}

/* ── Community Detail: List Mode (by Out-Degree) ─ */
function CommunityDetailList({ community, learnedNodes, toggleLearned, onStartLearning, pathMode, selectedTarget }) {
  if (!community) return null;
  const byDegree = {};
  community.nodes.forEach(n => { const d = n.outDegree ?? 0; if (!byDegree[d]) byDegree[d] = []; byDegree[d].push(n); });
  const sortedDegrees = Object.keys(byDegree).map(Number).sort((a, b) => b - a);
  const learnedCount = community.nodes.filter(n => learnedNodes.has(n.name)).length;
  const pct = community.size > 0 ? Math.round((learnedCount / community.size) * 100) : 0;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <CommunityHeader community={community} pct={pct} learnedCount={learnedCount} hint="Out-Degree 越高代表越基礎的知識，建議由上往下依序學習。" pathMode={pathMode} />
      <div className="space-y-4 mt-4">
        {sortedDegrees.map(degree => (
          <div
            key={degree}
            className={`bg-slate-900/60 rounded-xl border overflow-hidden ${byDegree[degree].some(n => n.name === selectedTarget?.name) ? 'border-amber-500/60 bg-amber-950/10' : 'border-slate-800'}`}
          >
            <div className="px-4 py-2 bg-slate-800/50 flex items-center gap-2 border-b border-slate-800">
              <span className={`px-2 py-0.5 rounded-full text-xs font-bold border ${degreeBg(degree)}`}>Out-Degree {degree}</span>
              <span className="text-xs text-slate-500">{degree > 5 ? '🏛️ 核心基礎' : degree > 2 ? '📗 中階知識' : degree > 0 ? '📘 進階知識' : '🎯 末端知識'}</span>
              <span className="ml-auto text-xs text-slate-600">{byDegree[degree].length} 個</span>
            </div>
            <div className="p-3 flex flex-wrap gap-2">
              {byDegree[degree].map(node => {
                const learned = learnedNodes.has(node.name);
                const isTarget = selectedTarget?.name === node.name;
                return (
                  <div key={node.name} className="group flex items-center gap-1">
                    <button onClick={() => toggleLearned(node.name)} className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all shrink-0 ${learned ? 'bg-emerald-500 border-emerald-400 text-white' : 'border-slate-600 hover:border-slate-400'}`} title={learned ? '標記為未學會' : '標記為已學會'}>
                      {learned && <span className="text-xs">✓</span>}
                    </button>
                    <button onClick={() => onStartLearning(node.name)} className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all hover:brightness-125 active:scale-95 ${learned ? 'bg-emerald-900/30 border-emerald-700/50 text-emerald-300' : 'bg-slate-800 border-slate-700 text-slate-300 hover:border-indigo-500 hover:text-indigo-300'}`}>
                      {isTarget && <span className="text-amber-300 mr-1">★</span>}
                      {node.name}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Shared header for community detail panels ─── */
function CommunityHeader({ community, pct, learnedCount, hint, pathMode }) {
  return (
    <div className="p-4 border-b border-slate-800 shrink-0">
      <div className="flex items-center gap-3 mb-2">
        <span className="w-4 h-4 rounded-full" style={{ background: commColor(community.community) }}></span>
        <h2 className="text-xl font-bold text-white">
          {pathMode === 'community' ? getCommunityName(community.community) : community.community}
          <span className="text-sm font-normal text-slate-500 ml-2">#{community.community}</span>
        </h2>
        <span className="px-2 py-0.5 bg-slate-800 rounded text-xs text-slate-400">{community.size} 個知識點</span>
        <span className="ml-auto text-xs text-slate-500">
          跨{pathMode === 'community' ? '主題' : '章節'}基礎度: <span className="text-indigo-400 font-bold">{community.interOutDegree}</span>
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex-1 max-w-xs h-2 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }}></div>
        </div>
        <span className="text-sm text-slate-400">{pct}% ({learnedCount}/{community.size})</span>
      </div>
      <p className="text-xs text-indigo-400 mt-2">💡 {hint}</p>
    </div>
  );
}

/* ══════════════════════════════════════════════════
   Tab 2: Path Planner View
   ══════════════════════════════════════════════════ */
function PathPlannerView({ searchQuery, setSearchQuery, setSearchResults, searchResults, selectedTarget, setSelectedTarget, plannedPath, planning, handlePlan, learnedNodes, toggleLearned, onStartLearning, pathMode }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6">
        {/* Title */}
        <div className="mb-6 text-center">
          <h2 className="text-2xl font-bold text-white mb-2">🧭 個人化學習路徑規劃</h2>
          <p className="text-slate-400">輸入你想學的目標知識點，系統會根據你已掌握的知識，規劃一條最佳學習路徑。</p>
        </div>

        {/* Search Box */}
        <div className="relative mb-6">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <input
                type="text"
                placeholder="搜尋目標知識點... (例如: SQL Injection, 防火牆, AES)"
                value={searchQuery}
                onChange={e => { setSearchQuery(e.target.value); setSelectedTarget(null) }}
                className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
              />
              {/* Autocomplete dropdown */}
              {searchResults.length > 0 && searchQuery.trim().length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-xl shadow-xl z-20 max-h-60 overflow-y-auto">
                  {searchResults.map(r => (
                    <button
                      key={r.name}
                      onClick={() => { setSelectedTarget(r); setSearchQuery(r.name); setSearchResults([]) }}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-700 transition-colors flex items-center justify-between border-b border-slate-700/50 last:border-0"
                    >
                      <span className="text-sm text-white font-medium">{r.name}</span>
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <span>社群 {r.community}</span>
                        {r.layer != null && <span>Layer {r.layer}</span>}
                        {learnedNodes.has(r.name) && <span className="text-emerald-400">✓ 已學</span>}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={handlePlan}
              disabled={!selectedTarget || planning}
              className={`px-6 py-3 rounded-xl font-bold text-sm transition-all shrink-0 ${selectedTarget && !planning ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-500/20' : 'bg-slate-700 text-slate-500 cursor-not-allowed'}`}
            >
              {planning ? '規劃中...' : '🚀 規劃路徑'}
            </button>
          </div>
          {selectedTarget && (
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="text-slate-500">已選目標:</span>
              <span className="px-2 py-0.5 bg-indigo-900/40 border border-indigo-700/50 rounded-full text-indigo-300 font-medium">{selectedTarget.name}</span>
              <span className="text-slate-600">· 社群 {selectedTarget.community}</span>
              <button onClick={() => { setSelectedTarget(null); setSearchQuery('') }} className="text-slate-600 hover:text-white text-xs ml-2">✕ 清除</button>
            </div>
          )}
        </div>

        {/* Planned Path Result */}
        {plannedPath && (
          <div className="mb-6">
            <PlannedPathResult
              result={plannedPath}
              learnedNodes={learnedNodes}
              pathMode={pathMode}
            />
          </div>
        )}

        {/* Current Knowledge Summary */}
        <div className="mb-6 p-4 bg-slate-900/60 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold text-slate-300">📋 你目前的知識基礎</h3>
            <span className="text-xs text-emerald-400 font-bold">{learnedNodes.size} 個已學會</span>
          </div>
          {learnedNodes.size > 0 ? (
            <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
              {Array.from(learnedNodes).map(name => (
                <span key={name} className="inline-flex items-center gap-1 px-2 py-1 bg-emerald-900/20 border border-emerald-800/30 rounded text-xs text-emerald-300">
                  ✓ {name}
                  <button onClick={() => toggleLearned(name)} className="text-emerald-600 hover:text-red-400 ml-0.5">×</button>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-600">尚未標記任何已學會的知識點。可以在「社群學習順序」中標記。</p>
          )}
        </div>

        
      </div>
    </div>
  )
}

/* ── Planned Path Result ───────────────────────── */
function PlannedPathResult({ result, learnedNodes, pathMode }) {

  if (result.error) {
    return (
      <div className="p-4 bg-red-900/20 border border-red-800 rounded-xl text-red-300 text-sm">
        ⚠️ {result.error}
      </div>
    )
  }

  if (!result.path || result.path.length === 0) {
    return (
      <div className="p-4 bg-slate-800 rounded-xl text-slate-400 text-sm text-center">
        找不到從目前知識到目標節點的學習路徑。
      </div>
    )
  }

  // Group nodes by community, preserving the order of first appearance
  const communityOrder = []
  const groups = {}
  result.path.forEach(node => {
    const cid = node.community ?? '未分類'
    if (!groups[cid]) {
      groups[cid] = []
      communityOrder.push(cid)
    }
    groups[cid].push(node)
  })

  const targetNode = result.path.find(n => n.name === result.target)
  const targetGroup = targetNode?.community ?? null
  const targetGroupNodes = targetGroup != null ? (groups[targetGroup] || []) : []
  const targetIndex = targetGroupNodes.findIndex(n => n.name === result.target)
  const prereqNodes = targetIndex >= 0 ? targetGroupNodes.slice(0, targetIndex) : []
  const prereqToLearn = prereqNodes.filter(n => !learnedNodes.has(n.name)).length
  const fallbackLearned = targetGroupNodes.filter(n => learnedNodes.has(n.name)).length
  const fallbackToLearn = targetGroupNodes.length - fallbackLearned
  const toLearnDisplay = targetIndex >= 0 ? prereqToLearn : (targetGroupNodes.length > 0 ? fallbackToLearn : result.to_learn)
  const scopeLabel = pathMode === 'chapter' ? '章節' : '社群'

  return (
    <div className="space-y-4">
      <div className="p-4 bg-indigo-950/30 rounded-xl border border-indigo-800/50">
        <h3 className="text-lg font-bold text-white mb-3">前往「{result.target}」的學習路徑</h3>
        <div className="space-y-1.5 text-sm">
          <div className="text-emerald-400">✓ 已學會 <span className="font-bold">{result.already_learned}</span></div>
          <div className="text-amber-400">📖 該{scopeLabel}需學習 <span className="font-bold">{toLearnDisplay}</span></div>
        </div>
      </div>
    </div>
  )
}
