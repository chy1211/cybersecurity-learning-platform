import React, { useState, useMemo, useCallback, memo, useEffect } from 'react';
import {
  ReactFlow, Background, Controls,
  Handle, Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import LearningMode from './LearningMode';
import api from '../services/api';
import { buildChapterTitleMap, parseUnitItems, extractUnitLabel, summarizeChapterCounts } from '../utils/chapterNameUtils';

const NODE_W = 172;
const NODE_H = 48;

const STATUS_CFG = {
  completed: { bg: '#6DCE9E', border: '#ffffff', icon: '✓', label: '已完成', dot: 'bg-emerald-400' },
  unlocked:  { bg: '#4C8EDA', border: '#ffffff', icon: '▶', label: '可學習', dot: 'bg-blue-400' },
  remedial:  { bg: '#F16667', border: '#ffffff', icon: '⚠', label: '需補強', dot: 'bg-red-400' },
  locked:    { bg: '#A5ABB6', border: '#ffffff', icon: '🔒', label: '鎖定中', dot: 'bg-slate-400' },
};

const MILESTONE_CFG = {
  beginner:     { label: '🏕️ 新手村 — 基礎知識', desc: 'Layer 0~1：核心概念與基礎術語', color: 'emerald' },
  intermediate: { label: '⚔️ 進階區 — 深度應用', desc: 'Layer 2~3：攻防技術與防禦機制', color: 'amber' },
  expert:       { label: '🏆 專家區 — 綜合實戰', desc: 'Layer 4+：高階整合與專家分析', color: 'rose' },
};

const summarizeUnits = (value) => {
  const items = parseUnitItems(value);
  const rawLabels = items.map(extractUnitLabel).filter(Boolean);
  const titleMap = buildChapterTitleMap(rawLabels);
  return summarizeChapterCounts(items, titleMap);
};

/* ── Custom Node for React Flow subgraph ─────────────── */
function SkillNodeInner({ data }) {
  const cfg = STATUS_CFG[data.status] || STATUS_CFG.locked;
  const isExternal = data.isExternal;
  
  const bg = isExternal ? '#1e293b' : cfg.bg;
  const border = isExternal ? '#475569' : cfg.border;
  const borderStyle = isExternal ? 'dashed' : 'solid';
  const color = isExternal ? '#94a3b8' : '#fff';
  const icon = isExternal ? '🔗' : cfg.icon;

  return (
    <div style={{
      width: NODE_W, height: NODE_H, background: bg,
      border: `2px ${borderStyle} ${data._selected ? '#ffffff' : border}`,
      borderRadius: 24, display: 'flex', alignItems: 'center', gap: 6,
      padding: '0 16px', color: '#ffffff', fontSize: 13, fontWeight: 700,
      boxShadow: data._selected ? `0 0 15px ${bg}` : 'none',
      cursor: 'pointer',
      transition: 'all 0.2s ease-in-out'
    }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0, pointerEvents: 'none' }} />
      <span style={{ flexShrink: 0 }}>{icon}</span>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{data.label}</span>
      <Handle type="source" position={Position.Right} style={{ opacity: 0, pointerEvents: 'none' }} />
    </div>
  );
}
const SkillNode = memo(SkillNodeInner);
const nodeTypes = { skill: SkillNode };

/* ── Dagre layout for subgraph ───────────────────────── */
function layoutSubgraph(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  
  const isLarge = nodes.length > 25;
  g.setGraph({
    rankdir: isLarge ? 'TB' : 'LR',
    nodesep: isLarge ? 30 : 20,
    ranksep: isLarge ? 60 : 80,
    acyclicer: 'greedy',
    ranker: 'tight-tree',
  });
  
  nodes.forEach(n => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach(e => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return {
    nodes: nodes.map(n => {
      const p = g.node(n.id);
      return { id: n.id, type: 'skill', position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 }, data: { ...n.data, _selected: false } };
    }),
    edges: edges.map(e => ({
      id: e.id || `${e.source}-${e.target}`, source: e.source, target: e.target,
      style: e.style || { stroke: '#475569', strokeWidth: 1.5 },
      markerEnd: { type: 'arrowclosed', color: '#475569', width: 14, height: 14 },
    })),
  };
}

/* ── Smart Group View (Tag Cloud vs ReactFlow) ─────────── */
function GroupGraphView({ group, data, edgesByTarget, edgesBySource, onNodeClick }) {
  const groupNodeIds = new Set(group.nodes.map(n => n.id));

  // 計算群組內部有幾條邊
  const internalEdgeCount = group.nodes.reduce((acc, n) => {
    const outEdges = (edgesBySource[n.id] || []).filter(e => groupNodeIds.has(e.target));
    return acc + outEdges.length;
  }, 0);

  // 邊太少（連結密度低）→ 用 Tag 雲，不用 ReactFlow
  const edgeDensity = internalEdgeCount / Math.max(group.nodes.length, 1);
  let useTagLayout = edgeDensity < 0.3 || group.nodes.length > 20;
  if (group.forceView === 'tagcloud') useTagLayout = true;
  if (group.forceView === 'reactflow') useTagLayout = false;

  if (useTagLayout) {
    return <TagCloudView nodes={group.nodes} onNodeClick={onNodeClick} />;
  }

  return <ReactFlowView group={group} data={data} edgesByTarget={edgesByTarget} edgesBySource={edgesBySource} onNodeClick={onNodeClick} />;
}

/* ── Tag Cloud View ──────────────────────────────────── */
function TagCloudView({ nodes, onNodeClick }) {
  // 按 topological_layer 分欄顯示
  const byLayer = {};
  nodes.forEach(n => {
    const l = n.data.topological_layer ?? 0;
    if (!byLayer[l]) byLayer[l] = [];
    byLayer[l].push(n);
  });

  return (
    <div className="p-4 space-y-3">
      {Object.entries(byLayer).sort(([a],[b]) => Number(a)-Number(b)).map(([layer, layerNodes]) => (
        <div key={layer} className="flex flex-wrap gap-2 items-start">
          <span className="text-xs text-slate-500 w-12 shrink-0 pt-1.5 font-bold">Layer {layer}</span>
          <div className="flex flex-wrap gap-2 flex-1">
            {layerNodes.map(node => {
              const cfg = STATUS_CFG[node.data.status] || STATUS_CFG.locked;
              return (
                <button key={node.id} onClick={() => onNodeClick(node)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all hover:brightness-125 active:scale-95"
                  style={{ background: cfg.bg + '99', borderColor: cfg.border, color: '#fff' }}>
                  {cfg.icon} {node.data.label}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── ReactFlow View ──────────────────────────────────── */
function ReactFlowView({ group, data, edgesByTarget, edgesBySource, onNodeClick }) {
  const { nodes, edges } = useMemo(() => {
    const groupNodeIds = new Set(group.nodes.map(n => n.id));
    const finalNodes = new Map();
    const finalEdges = [];
    
    group.nodes.forEach(n => finalNodes.set(n.id, { ...n, data: { ...n.data, isExternal: false } }));
    
    group.nodes.forEach(n => {
      // internal edges out
      const outEdges = edgesBySource[n.id] || [];
      let externalOutCount = 0;
      outEdges.forEach(e => {
        if (groupNodeIds.has(e.target)) {
          finalEdges.push(e);
        } else if (externalOutCount < 1) {
          externalOutCount++;
          const extNode = data.nodes.find(x => x.id === e.target);
          if (extNode && !finalNodes.has(extNode.id)) {
            finalNodes.set(extNode.id, { ...extNode, data: { ...extNode.data, isExternal: true } });
          }
          finalEdges.push({ ...e, style: { stroke: '#475569', strokeWidth: 1.5, strokeDasharray: '4 4' } });
        }
      });
      
      // internal edges in
      const inEdges = edgesByTarget[n.id] || [];
      let externalInCount = 0;
      inEdges.forEach(e => {
        if (!groupNodeIds.has(e.source) && externalInCount < 1) {
          externalInCount++;
          const extNode = data.nodes.find(x => x.id === e.source);
          if (extNode && !finalNodes.has(extNode.id)) {
            finalNodes.set(extNode.id, { ...extNode, data: { ...extNode.data, isExternal: true } });
          }
          finalEdges.push({ ...e, style: { stroke: '#475569', strokeWidth: 1.5, strokeDasharray: '4 4' } });
        }
      });
    });
    
    return layoutSubgraph(Array.from(finalNodes.values()), finalEdges);
  }, [group, data, edgesByTarget, edgesBySource]);

  return (
    <div style={{ height: Math.max(300, Math.min(800, nodes.length * 60)), width: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2} maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        style={{ background: 'transparent' }}
        defaultEdgeOptions={{ type: 'smoothstep' }}
        nodesDraggable={false} nodesConnectable={false}
        onNodeClick={(_, node) => onNodeClick(node)}
      >
        <Background color="#1e293b" gap={24} size={1} />
        <Controls position="bottom-left" style={{ background: '#1e293b', borderColor: '#334155', borderRadius: 8 }} />
      </ReactFlow>
    </div>
  );
}

/* ── Grouping logic per strategy ─────────────────────── */
function computeGroups(data, edgesBySource, edgesByTarget) {
  if (!data?.nodes) return [];

  const layers = {};
  data.nodes.forEach(node => {
    const l = node.data.level ?? 0;
    if (!layers[l]) {
      layers[l] = { key: `layer_${l}`, label: `拓樸層級 ${l}`, nodes: [], sortOrder: l, groupType: 0 };
    }
    layers[l].nodes.push(node);
  });

  return Object.values(layers).sort((a, b) => a.sortOrder - b.sortOrder);
}

/* ── Main Component ──────────────────────────────────── */
export default function SkillTreeComponent({ data, onRefresh }) {
  const [selectedNode, setSelectedNode] = useState(null);
  const [learningModeNode, setLearningModeNode] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState(new Set());
  const [egoRelations, setEgoRelations] = useState(null);

  useEffect(() => {
    if (selectedNode) {
      setEgoRelations(null);
      api.getNodeNeighbors(selectedNode.id, 20).then(res => {
        setEgoRelations(res.relations || []);
      }).catch(err => {
        console.error("Failed to fetch node neighbors:", err);
        setEgoRelations([]);
      });
    } else {
      setEgoRelations(null);
    }
  }, [selectedNode]);

  const { edgesByTarget, edgesBySource } = useMemo(() => {
    const tgtMap = {};
    const srcMap = {};
    if (data?.edges) {
      data.edges.forEach(edge => {
        if (!tgtMap[edge.target]) tgtMap[edge.target] = [];
        tgtMap[edge.target].push(edge);
        if (!srcMap[edge.source]) srcMap[edge.source] = [];
        srcMap[edge.source].push(edge);
      });
    }
    return { edgesByTarget: tgtMap, edgesBySource: srcMap };
  }, [data]);

  const groups = useMemo(() => computeGroups(data, edgesBySource, edgesByTarget), [data, edgesBySource, edgesByTarget]);

  const connectedIds = useMemo(() => {
    if (!selectedNode) return new Set();
    const ids = new Set([selectedNode.id]);
    (edgesByTarget[selectedNode.id] || []).forEach(e => ids.add(e.source));
    (edgesBySource[selectedNode.id] || []).forEach(e => ids.add(e.target));
    return ids;
  }, [selectedNode, edgesByTarget, edgesBySource]);


  // Prerequisites & dependents
  const { prerequisites, dependents } = useMemo(() => {
    if (!selectedNode) return { prerequisites: [], dependents: [] };
    const prereqs = (edgesByTarget[selectedNode.id] || []).map(e => data.nodes.find(n => n.id === e.source)).filter(Boolean);
    const deps = (edgesBySource[selectedNode.id] || []).map(e => data.nodes.find(n => n.id === e.target)).filter(Boolean);
    return { prerequisites: prereqs, dependents: deps };
  }, [selectedNode, edgesByTarget, edgesBySource, data.nodes]);

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return null;
    const q = searchQuery.toLowerCase();
    return data.nodes.filter(n => n.data.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
  }, [searchQuery, data.nodes]);

  const toggleGroup = (key) => setCollapsedGroups(prev => { const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next; });
  
  const handleJumpToGroup = (node) => {
    if (!node) return;
    let targetKey = null;
    let parentKey = null;

    for (const ch of groups) {
      if (ch.subGroups) {
        for (const sub of ch.subGroups) {
          if (sub.nodes.some(n => n.id === node.id)) {
            targetKey = sub.key;
            parentKey = ch.key;
            break;
          }
        }
      } else {
        if (ch.nodes.some(n => n.id === node.id)) {
          targetKey = ch.key;
        }
      }
      if (targetKey) break;
    }

    if (targetKey !== null) {
      setCollapsedGroups(prev => {
        const next = new Set(prev);
        next.delete(targetKey);
        if (parentKey) next.delete(parentKey);
        return next;
      });
      setTimeout(() => {
        const el = document.getElementById(`group-${targetKey}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          el.classList.add('ring-2', 'ring-indigo-500');
          setTimeout(() => el.classList.remove('ring-2', 'ring-indigo-500'), 2000);
        }
      }, 100);
    }
  };

  const handleNodeClick = (node) => { 
    setSelectedNode(prev => prev?.id === node.id ? null : node); 
  };
  const handleStartLearning = () => { if (selectedNode && selectedNode.data.status !== 'locked') { setLearningModeNode(selectedNode); setSelectedNode(null); } };
  const handleLearningComplete = () => { setLearningModeNode(null); if (onRefresh) onRefresh(); };

  if (learningModeNode) {
    return <LearningMode chapter={learningModeNode} onClose={() => setLearningModeNode(null)} onComplete={handleLearningComplete} />;
  }

  const getStatusStyle = (status) => STATUS_CFG[status] || STATUS_CFG.locked;

  const renderNodeTag = (node, showDim = true) => {
    const status = node.data.status || 'locked';
    const style = getStatusStyle(status);
    const isSelected = selectedNode?.id === node.id;
    const isConnected = connectedIds.has(node.id);
    const dimmed = showDim && selectedNode && !isSelected && !isConnected;
    return (
      <button key={node.id} onClick={() => handleNodeClick(node)}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium transition-all duration-150 cursor-pointer select-none hover:brightness-125 active:scale-95 ${isSelected ? 'ring-2 ring-indigo-400 scale-105 z-10' : ''} ${dimmed ? 'opacity-25' : 'opacity-100'}`}
        style={{ background: style.bg + '99', borderColor: style.border, color: '#fff' }}>
        <span className="text-xs">{style.icon}</span>
        <span className="whitespace-nowrap">{node.data.label}</span>
      </button>
    );
  };

  return (
    <div className="flex h-[calc(100vh-170px)]">
      {/* Main scrollable area */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {/* Top bar */}
        <div className="sticky top-0 z-20 flex flex-wrap items-center gap-4 p-3 bg-slate-900/95 backdrop-blur-sm border-b border-slate-800 text-xs text-slate-400">
          <div className="flex items-center gap-3">
            <span className="font-bold text-slate-300">圖例：</span>
            {Object.entries(STATUS_CFG).map(([key, cfg]) => (
              <span key={key} className="flex items-center gap-1"><span className={`w-2.5 h-2.5 rounded ${cfg.dot} inline-block`}></span> {cfg.label}</span>
            ))}
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <input type="text" placeholder="搜尋節點..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              className="px-3 py-1 bg-slate-800 border border-slate-700 rounded-md text-white text-xs placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-48" />
            <span className="text-slate-500">共 {data.nodes.length} 個節點 · {groups.length} 個分組</span>
          </div>
        </div>

        {/* Search results */}
        {searchResults && (
          <div className="m-4 p-4 bg-indigo-950/30 rounded-lg border border-indigo-800">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-indigo-300">搜尋結果：找到 {searchResults.length} 個節點</h3>
              <button onClick={() => setSearchQuery('')} className="text-xs text-indigo-400 hover:text-white">清除</button>
            </div>
            <div className="flex flex-wrap gap-2">
              {searchResults.slice(0, 50).map(node => renderNodeTag(node, false))}
              {searchResults.length > 50 && <span className="text-xs text-slate-500 self-center">...還有 {searchResults.length - 50} 個</span>}
            </div>
          </div>
        )}



        {/* Group sections */}
        <div className="p-4 space-y-3">
          {groups.map((group) => {
            const isCollapsed = collapsedGroups.has(group.key);
            const counts = { completed: 0, unlocked: 0, locked: 0, remedial: 0 };
            group.nodes.forEach(n => { const s = n.data.status || 'locked'; counts[s] = (counts[s] || 0) + 1; });

            // Milestone-specific styling
            const borderColor = group.color === 'emerald' ? 'border-emerald-900/50' :
                                group.color === 'amber'   ? 'border-amber-900/50' :
                                group.color === 'rose'    ? 'border-rose-900/50' : 'border-slate-800';
            const headerBg = group.color === 'emerald' ? 'hover:bg-emerald-950/30' :
                             group.color === 'amber'   ? 'hover:bg-amber-950/30' :
                             group.color === 'rose'    ? 'hover:bg-rose-950/30' : 'hover:bg-slate-800/40';

            return (
              <div key={group.key} id={`group-${group.key}`} className={`bg-slate-900/50 rounded-xl border ${borderColor} overflow-hidden transition-all duration-500`}>
                <button onClick={() => toggleGroup(group.key)}
                  className={`w-full flex items-center justify-between px-5 py-3 ${headerBg} transition-colors text-left`}>
                  <div className="flex items-center gap-3">
                    <span className={`text-slate-500 text-xs transition-transform duration-200 ${isCollapsed ? '' : 'rotate-90'}`}>▶</span>
                    <div>
                      <span className="text-white font-bold text-sm">{group.label}</span>
                      {group.desc && <span className="text-slate-500 text-xs ml-2">— {group.desc}</span>}
                    </div>
                    <span className="text-slate-500 text-xs">({group.nodes.length} 個節點)</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {counts.completed > 0 && <span className="px-2 py-0.5 rounded-full bg-emerald-900/50 text-emerald-400 font-medium">✓ {counts.completed}</span>}
                    {counts.unlocked > 0 && <span className="px-2 py-0.5 rounded-full bg-blue-900/50 text-blue-400 font-medium">▶ {counts.unlocked}</span>}
                    {counts.locked > 0 && <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-500 font-medium">🔒 {counts.locked}</span>}
                    {counts.remedial > 0 && <span className="px-2 py-0.5 rounded-full bg-red-900/50 text-red-400 font-medium">⚠ {counts.remedial}</span>}
                  </div>
                </button>
                {!isCollapsed && (
                  <div className="bg-slate-950 border-t border-slate-800 p-3 space-y-3">
                    {group.subGroups ? (
                      group.subGroups.map(sub => {
                        const isSubCollapsed = collapsedGroups.has(sub.key);
                        return (
                          <div key={sub.key} id={`group-${sub.key}`} className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden transition-all duration-300">
                            <button onClick={() => toggleGroup(sub.key)} className="w-full flex items-center px-4 py-2 hover:bg-slate-800 text-left transition-colors">
                              <span className={`text-slate-500 text-xs mr-2 transition-transform duration-200 ${isSubCollapsed ? '' : 'rotate-90'}`}>▶</span>
                              <span className="text-sm font-semibold text-slate-300">{sub.label}</span>
                              <span className="ml-auto text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">{sub.nodes.length}</span>
                            </button>
                            {!isSubCollapsed && (
                              <div className="border-t border-slate-700">
                                <GroupGraphView 
                                  group={sub} 
                                  data={data} 
                                  edgesByTarget={edgesByTarget} 
                                  edgesBySource={edgesBySource} 
                                  onNodeClick={handleNodeClick} 
                                />
                              </div>
                            )}
                          </div>
                        )
                      })
                    ) : (
                      <GroupGraphView 
                        group={group} 
                        data={data} 
                        edgesByTarget={edgesByTarget} 
                        edgesBySource={edgesBySource} 
                        onNodeClick={handleNodeClick} 
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail side panel */}
      {selectedNode && (
        <div className="w-80 border-l border-slate-800 bg-slate-900 overflow-y-auto custom-scrollbar shrink-0">
          <div className="p-5">
            <div className="flex justify-between items-start mb-4">
              <div>
                <p className="text-xs text-slate-500 mb-1">第 {selectedNode.data.level ?? 0} 層</p>
                <h3 className="text-lg font-bold text-white">{selectedNode.data.label}</h3>
              </div>
              <button onClick={() => setSelectedNode(null)} className="text-slate-500 hover:text-white text-lg">✕</button>
            </div>

            {/* Status badge */}
            {(() => { const s = selectedNode.data.status || 'locked'; const cfg = getStatusStyle(s); return (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold mb-3 border" style={{ background: cfg.bg + '40', borderColor: cfg.border, color: cfg.border }}>
                <span className="w-2 h-2 rounded-full" style={{ background: cfg.bg }}></span>{cfg.label}
              </span>); })()}

            <div className="flex flex-wrap gap-1.5 mb-4">
              {selectedNode.data.top_3_units && summarizeUnits(selectedNode.data.top_3_units).length > 0 && (
                <span className="px-2 py-0.5 bg-slate-800 rounded text-xs text-slate-400">📑 主要章節: {summarizeUnits(selectedNode.data.top_3_units).map((unit) => `${unit.unit} (${unit.count})`).join(', ')}</span>
              )}
              {selectedNode.data.community !== undefined && (
                <span className="px-2 py-0.5 bg-slate-800 rounded text-xs text-slate-400">🔬 社群 {selectedNode.data.community}</span>
              )}
            </div>

            <p className="text-sm text-slate-400 mb-4 leading-relaxed">{selectedNode.data.description || '開始這個單元的學習'}</p>

            {selectedNode.data.isExternal && (
              <button onClick={() => handleJumpToGroup(selectedNode)}
                className="w-full mb-3 py-2 rounded-lg font-bold text-sm bg-slate-800 hover:bg-slate-700 text-indigo-400 border border-slate-700 transition-colors">
                🔗 跳轉至該群組
              </button>
            )}

            <button onClick={handleStartLearning} disabled={selectedNode.data.status === 'locked'}
              className={`w-full py-3 rounded-lg font-bold transition-all uppercase tracking-wider text-sm mb-6 ${
                selectedNode.data.status !== 'locked' ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-500/20 active:scale-95' : 'bg-slate-700 text-slate-500 cursor-not-allowed'
              }`}>
              {selectedNode.data.status !== 'locked' ? 'START HACKING' : 'LOCKED'}
            </button>

            {prerequisites.length > 0 && (
              <div className="mb-5">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">先備知識 ({prerequisites.length})</h4>
                <div className="space-y-1">{prerequisites.map(n => { const s = getStatusStyle(n.data.status || 'locked'); return (
                  <button key={n.id} onClick={() => handleNodeClick(n)} className="w-full text-left p-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm flex items-center gap-2 group transition-colors">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.bg }}></span>
                    <span className="text-slate-300 group-hover:text-white truncate">↑ {n.data.label}</span>
                  </button>); })}</div>
              </div>
            )}

            {dependents.length > 0 && (
              <div>
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">後續學習 ({dependents.length})</h4>
                <div className="space-y-1">{dependents.map(n => { const s = getStatusStyle(n.data.status || 'locked'); return (
                  <button key={n.id} onClick={() => handleNodeClick(n)} className="w-full text-left p-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm flex items-center gap-2 group transition-colors">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.bg }}></span>
                    <span className="text-slate-300 group-hover:text-white truncate">↓ {n.data.label}</span>
                  </button>); })}</div>
              </div>
            )}

            {egoRelations !== null && egoRelations.length > 0 && (
              <div className="mt-6 mb-5 pt-4 border-t border-slate-800">
                <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-2">Neo4j 關聯節點 ({egoRelations.length})</h4>
                <div className="space-y-1 max-h-48 overflow-y-auto custom-scrollbar">
                  {egoRelations.map((rel, idx) => (
                    <div key={idx} className="p-2 bg-slate-800/50 rounded-lg text-xs flex flex-col gap-1 border border-slate-700/50">
                      <div className="text-slate-500 font-mono text-[10px]">{rel.source === selectedNode.id ? '⭢ 出邊' : '⭠ 入邊'} · {rel.relationship}</div>
                      <div className="text-slate-300 font-medium">{rel.source === selectedNode.id ? rel.target : rel.source}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>
        </div>
      )}
    </div>
  );
}
