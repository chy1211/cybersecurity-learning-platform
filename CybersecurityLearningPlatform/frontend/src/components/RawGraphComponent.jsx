import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import api from '../services/api';
import {
  NEO4J_GRAPH_BACKGROUND,
  NEO4J_LABEL_COLORS,
  Neo4jGraphShell,
  createNeo4jCollisionForce,
  createNeo4jSpokeForce,
  drawNeo4jLinkLabel,
  drawNeo4jNode,
  getNeo4jNodeColor,
} from './Neo4jGraphShell';

const TYPE_COLORS = NEO4J_LABEL_COLORS;
const getEndpointId = (endpoint) => (typeof endpoint === 'object' ? endpoint.id : endpoint);
const getLinkKey = (link) => `${getEndpointId(link.source)}--${link.name || ''}--${getEndpointId(link.target)}`;
const getRawNodeLabel = (node) => node?.label || node?.name || node?.id || '';

const hashToUnit = (value, salt = 0) => {
  const str = `${value}:${salt}`;
  let hash = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
};

function prepareNeo4jRawGraphLayout(nodes, links) {
  const degree = new Map();
  links.forEach((link) => {
    const source = getEndpointId(link.source);
    const target = getEndpointId(link.target);
    degree.set(source, (degree.get(source) || 0) + 1);
    degree.set(target, (degree.get(target) || 0) + 1);
  });

  const ringNodes = [];
  const coreNodes = [];
  const clonedNodes = nodes.map((node) => {
    const next = { ...node, __degree: degree.get(node.id) || 0 };
    if (next.__degree <= 2) ringNodes.push(next);
    else coreNodes.push(next);
    return next;
  });

  ringNodes.sort((a, b) => String(a.id).localeCompare(String(b.id)));
  ringNodes.forEach((node, index) => {
    const angle = ((Math.PI * 2) * index) / Math.max(1, ringNodes.length);
    const jitter = (hashToUnit(node.id, 2) - 0.5) * 120;
    const radius = 3500 + jitter;
    node.x = Math.cos(angle) * radius;
    node.y = Math.sin(angle) * radius;
    node.__neo4jOrbitRadius = radius;
  });

  coreNodes.forEach((node) => {
    const angle = hashToUnit(node.id, 3) * Math.PI * 2;
    const degreeWeight = Math.min(node.__degree, 18) / 18;
    const radius = 90 + Math.sqrt(hashToUnit(node.id, 4)) * (850 - degreeWeight * 330);
    node.x = Math.cos(angle) * radius;
    node.y = Math.sin(angle) * radius;
    node.__neo4jOrbitRadius = null;
  });

  return clonedNodes;
}

function createNeo4jOrbitForce(strength = 0.035) {
  let nodes = [];
  const force = (alpha) => {
    nodes.forEach((node, index) => {
      if (!node.__neo4jOrbitRadius) return;
      const angle = ((Math.PI * 2) * index) / nodes.length;
      const targetX = Math.cos(angle) * node.__neo4jOrbitRadius;
      const targetY = Math.sin(angle) * node.__neo4jOrbitRadius;
      node.vx = (node.vx || 0) + (targetX - node.x) * strength * alpha;
      node.vy = (node.vy || 0) + (targetY - node.y) * strength * alpha;
    });
  };
  force.initialize = (nextNodes) => {
    nodes = nextNodes || [];
  };
  return force;
}

function drawNeo4jOverviewNode(node, ctx, globalScale, options = {}) {
  const radius = (options.active ? 4.2 : 2.2) / Math.max(globalScale, 0.001);
  ctx.save();
  ctx.globalAlpha = options.dimmed ? 0.15 : 1;
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
  ctx.fillStyle = getNeo4jNodeColor(node);
  ctx.fill();
  ctx.restore();
}

export default function RawGraphComponent() {
  const [rawGraphData, setRawGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedTypes, setSelectedTypes] = useState(new Set());
  const [availableTypes, setAvailableTypes] = useState([]);
  const [selectedRelations, setSelectedRelations] = useState(new Set());
  const [availableRelations, setAvailableRelations] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [focusedNode, setFocusedNode] = useState(null);
  const [detailNode, setDetailNode] = useState(null);
  const [hoverNode, setHoverNode] = useState(null);
  const [hoverLink, setHoverLink] = useState(null);
  const [highlightNodes, setHighlightNodes] = useState(new Set());
  const [highlightLinks, setHighlightLinks] = useState(new Set());
  const fgRef = useRef();
  const [typesCollapsed, setTypesCollapsed] = useState(false);
  const [relsCollapsed, setRelsCollapsed] = useState(false);

  useEffect(() => {
    api.getRawKnowledgeGraph()
      .then(data => {
        const links = data.edges.map(e => ({
          source: e.source,
          target: e.target,
          name: e.relationship
        }));
        setRawGraphData({ nodes: prepareNeo4jRawGraphLayout(data.nodes, links), links });
        
        const types = new Set(data.nodes.map(n => n.type || 'Concept'));
        const typesArray = Array.from(types).sort();
        setAvailableTypes(typesArray);
        setSelectedTypes(new Set(typesArray));
        
        const rels = new Set(links.map(l => l.name));
        const relsArray = Array.from(rels).sort();
        setAvailableRelations(relsArray);
        setSelectedRelations(new Set(relsArray));
        
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  }, []);

  const filteredGraphData = useMemo(() => {
    let nodes = rawGraphData.nodes.filter(n => selectedTypes.has(n.type || 'Concept'));
    let nodeIds = new Set(nodes.map(n => n.id));
    let links = rawGraphData.links.filter(l => {
      const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
      const targetId = typeof l.target === 'object' ? l.target.id : l.target;
      return nodeIds.has(sourceId) && nodeIds.has(targetId) && selectedRelations.has(l.name);
    });

    if (focusedNode) {
      const neighborIds = new Set([focusedNode.id]);
      links.forEach(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        if (sourceId === focusedNode.id) neighborIds.add(targetId);
        if (targetId === focusedNode.id) neighborIds.add(sourceId);
      });
      nodes = nodes.filter(n => neighborIds.has(n.id));
      nodeIds = new Set(nodes.map(n => n.id));
      links = links.filter(l => {
        const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
        const targetId = typeof l.target === 'object' ? l.target.id : l.target;
        return nodeIds.has(sourceId) && nodeIds.has(targetId);
      });
    }

    return { nodes, links };
  }, [rawGraphData, selectedTypes, selectedRelations, focusedNode]);

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return rawGraphData.nodes
      .filter(n => String(n.id).toLowerCase().includes(q) || getRawNodeLabel(n).toLowerCase().includes(q))
      .slice(0, 10);
  }, [searchQuery, rawGraphData.nodes]);

  useEffect(() => {
    if (fgRef.current) {
      const nodeCount = filteredGraphData.nodes.length;
      const isFocused = Boolean(focusedNode);
      const showNeo4jOverview = !isFocused && nodeCount > 800;
      fgRef.current.d3Force('charge')
        .strength(showNeo4jOverview ? -400 : isFocused ? -1900 : -1600)
        .distanceMax(showNeo4jOverview ? 2000 : isFocused ? 900 : 1300);
      fgRef.current.d3Force('link').distance(showNeo4jOverview ? 220 : isFocused ? 270 : 230);
      fgRef.current.d3Force('center').strength(showNeo4jOverview ? 0.005 : 0.03);
      fgRef.current.d3Force('neo4jOrbit', showNeo4jOverview ? createNeo4jOrbitForce(0.04) : null);
      fgRef.current.d3Force('neo4jSpokes', showNeo4jOverview ? null : createNeo4jSpokeForce(filteredGraphData.links, isFocused ? 260 : 240, 0.055));
      fgRef.current.d3Force('neo4jCollide', !showNeo4jOverview && nodeCount <= 700 ? createNeo4jCollisionForce(46, 18) : null);
      fgRef.current.d3ReheatSimulation();
    }
  }, [filteredGraphData, focusedNode]);

  const handleNodeHover = (node) => {
    const nextNodes = new Set();
    const nextLinks = new Set();
    if (node) {
      nextNodes.add(node.id);
      filteredGraphData.links.forEach(link => {
        const sourceId = getEndpointId(link.source);
        const targetId = getEndpointId(link.target);
        if (sourceId === node.id || targetId === node.id) {
          nextLinks.add(getLinkKey(link));
          nextNodes.add(sourceId);
          nextNodes.add(targetId);
        }
      });
    }
    setHoverNode(node || null);
    setHighlightNodes(nextNodes);
    setHighlightLinks(nextLinks);
  };

  const handleNodeClick = useCallback((node) => {
    setDetailNode(node);
    setFocusedNode(prev => (prev?.id === node.id ? null : node));
  }, []);

  const handleLinkHover = useCallback(link => {
    const nextNodes = new Set();
    const nextLinks = new Set();
    if (link) {
      nextLinks.add(getLinkKey(link));
      const sourceId = getEndpointId(link.source);
      const targetId = getEndpointId(link.target);
      nextNodes.add(sourceId);
      nextNodes.add(targetId);
    }
    setHighlightNodes(nextNodes);
    setHighlightLinks(nextLinks);
    setHoverLink(link || null);
  }, []);

  const handleLinkClick = useCallback(link => {
    const sourceId = getEndpointId(link.source);
    const targetId = getEndpointId(link.target);
    setHoverLink(link);
    setHoverNode(null);
    const nextNodes = new Set([sourceId, targetId]);
    const nextLinks = new Set([getLinkKey(link)]);
    setHighlightNodes(nextNodes);
    setHighlightLinks(nextLinks);
    if (fgRef.current && link.source?.x !== undefined && link.target?.x !== undefined) {
      const midX = (link.source.x + link.target.x) / 2;
      const midY = (link.source.y + link.target.y) / 2;
      fgRef.current.centerAt(midX, midY, 500);
    }
  }, []);

  const handleFocusNode = useCallback((node) => {
    setFocusedNode(prev => (prev?.id === node.id ? null : node));
    setDetailNode(node);
    setSearchQuery('');
  }, []);

  const handleBackgroundClick = useCallback(() => {
    setFocusedNode(null);
    setDetailNode(null);
    setHoverLink(null);
  }, []);

  const handleSearchSelect = useCallback((node) => {
    setSearchQuery('');
    setDetailNode(node);
    setFocusedNode(node);
  }, []);

  const toggleType = (type) => {
    const newSelected = new Set(selectedTypes);
    if (newSelected.has(type)) newSelected.delete(type);
    else newSelected.add(type);
    setSelectedTypes(newSelected);
  };

  const toggleAllTypes = () => {
    setSelectedTypes(selectedTypes.size === availableTypes.length ? new Set() : new Set(availableTypes));
  };

  const toggleRelation = (rel) => {
    const newSelected = new Set(selectedRelations);
    if (newSelected.has(rel)) newSelected.delete(rel);
    else newSelected.add(rel);
    setSelectedRelations(newSelected);
  };

  const toggleAllRelations = () => {
    setSelectedRelations(selectedRelations.size === availableRelations.length ? new Set() : new Set(availableRelations));
  };

  const getNodeNeighbors = useCallback((nodeId) => {
    if (!nodeId) return { incoming: [], outgoing: [] };
    const incoming = [];
    const outgoing = [];
    rawGraphData.links.forEach(l => {
      const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
      const targetId = typeof l.target === 'object' ? l.target.id : l.target;
      if (sourceId === nodeId) outgoing.push({ node: targetId, rel: l.name });
      if (targetId === nodeId) incoming.push({ node: sourceId, rel: l.name });
    });
    return { incoming, outgoing };
  }, [rawGraphData.links]);

  useEffect(() => {
    if (!fgRef.current || filteredGraphData.nodes.length === 0) return;
    fgRef.current.d3ReheatSimulation();
    const timeoutId = window.setTimeout(() => {
      fgRef.current?.zoomToFit(500, focusedNode ? 80 : 36);
    }, focusedNode ? 900 : 500);
    return () => window.clearTimeout(timeoutId);
  }, [focusedNode, filteredGraphData.nodes.length, filteredGraphData.links.length]);

  if (loading) {
    return <div className="text-white text-center p-10">載入全知識圖譜中...</div>;
  }

  return (
    <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0">
      {/* Filter Panel */}
      <div className="w-full lg:w-64 bg-slate-900 border border-slate-700 rounded-lg p-4 h-auto lg:h-full overflow-y-auto shrink-0 custom-scrollbar">
        {/* Types Filter */}
        <div className="flex justify-between items-center mb-3">
          <button 
            onClick={() => setTypesCollapsed(!typesCollapsed)}
            className="flex items-center gap-2 text-white font-bold hover:text-indigo-400 transition-colors"
          >
            <span className="text-xs text-slate-500 transition-transform" style={{ transform: typesCollapsed ? 'rotate(-90deg)' : 'rotate(0)' }}>▼</span>
            過濾節點類別
          </button>
          <button 
            onClick={toggleAllTypes}
            className="text-xs text-indigo-400 hover:text-indigo-300"
          >
            {selectedTypes.size === availableTypes.length ? '全不選' : '全選'}
          </button>
        </div>
        {!typesCollapsed && (
        <div className="space-y-2 grid grid-cols-2 lg:grid-cols-1 mb-6">
          {availableTypes.map(type => (
            <label key={type} className="flex items-center space-x-2 cursor-pointer group select-none">
              <input 
                type="checkbox" 
                checked={selectedTypes.has(type)}
                onChange={() => toggleType(type)}
                className="form-checkbox h-4 w-4 text-indigo-600 rounded bg-slate-800 border-slate-600"
              />
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: TYPE_COLORS[type] || TYPE_COLORS.default }} />
              <span className="text-slate-300 text-sm group-hover:text-white truncate">{type}</span>
            </label>
          ))}
        </div>
        )}

        {/* Relations Filter */}
        <div className="flex justify-between items-center mb-3 pt-4 border-t border-slate-700">
          <button 
            onClick={() => setRelsCollapsed(!relsCollapsed)}
            className="flex items-center gap-2 text-white font-bold hover:text-indigo-400 transition-colors"
          >
            <span className="text-xs text-slate-500 transition-transform" style={{ transform: relsCollapsed ? 'rotate(-90deg)' : 'rotate(0)' }}>▼</span>
            過濾關係連線
          </button>
          <button 
            onClick={toggleAllRelations}
            className="text-xs text-indigo-400 hover:text-indigo-300"
          >
            {selectedRelations.size === availableRelations.length ? '全不選' : '全選'}
          </button>
        </div>
        {!relsCollapsed && (
        <div className="space-y-2 grid grid-cols-2 lg:grid-cols-1">
          {availableRelations.map(rel => (
            <label key={rel} className="flex items-center space-x-2 cursor-pointer group select-none">
              <input 
                type="checkbox" 
                checked={selectedRelations.has(rel)}
                onChange={() => toggleRelation(rel)}
                className="form-checkbox h-4 w-4 text-indigo-600 rounded bg-slate-800 border-slate-600"
              />
              <span className="text-slate-300 text-sm group-hover:text-white truncate">{rel}</span>
            </label>
          ))}
        </div>
        )}

        <div className="mt-6 pt-4 border-t border-slate-700 text-slate-400 text-xs">
          目前顯示節點: {filteredGraphData.nodes.length} <br/>
          目前顯示連線: {filteredGraphData.links.length}
        </div>
      </div>

      {/* Graph Area */}
      <div className="flex-1 min-w-0 h-[600px] lg:h-[800px]">
        <Neo4jGraphShell
          title="neo4j$"
          subtitle={`${filteredGraphData.nodes.length} nodes · ${filteredGraphData.links.length} relationships`}
          graphData={filteredGraphData}
          loading={false}
          onZoomIn={() => fgRef.current?.zoom(fgRef.current.zoom() * 1.5, 300)}
          onZoomOut={() => fgRef.current?.zoom(fgRef.current.zoom() / 1.5, 300)}
          onFit={() => fgRef.current?.zoomToFit(400, 60)}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          searchResults={searchResults}
          onSearchSelect={handleSearchSelect}
          overlay={
            hoverNode ? (
            <div className="absolute top-14 left-4 z-10 bg-[#202428]/95 backdrop-blur-md p-4 rounded-md border shadow-xl max-w-sm pointer-events-none" style={{ borderColor: getNeo4jNodeColor(hoverNode) }}>
              <div className="flex items-center gap-2 mb-2">
                <span className="w-3 h-3 rounded-full" style={{ backgroundColor: getNeo4jNodeColor(hoverNode) }} />
                <h4 className="text-base font-bold text-white">{hoverNode.id}</h4>
              </div>
              <p className="text-xs text-[#9aa3af]">Type: {hoverNode.type || 'Concept'}</p>
              <p className="text-xs text-[#9aa3af] mt-2">點擊節點查看詳情，聚焦功能維持原本行為。</p>
            </div>
            ) : hoverLink ? (
            <div className="absolute top-14 left-4 z-10 bg-[#202428]/95 backdrop-blur-md p-4 rounded-md border border-[#9aa3af] shadow-xl max-w-sm pointer-events-none">
              <h4 className="text-base font-bold text-white mb-2 flex items-center gap-2">
                <span className="text-[#9aa3af]">─▶</span>
                {hoverLink.name || hoverLink.relationship || hoverLink.type || 'relationship'}
              </h4>
              <div className="space-y-1 text-sm">
                <p className="text-[#57C7E3]">來源: {getRawNodeLabel(typeof hoverLink.source === 'object' ? hoverLink.source : { id: hoverLink.source })}</p>
                <p className="text-[#6DCE9E]">目標: {getRawNodeLabel(typeof hoverLink.target === 'object' ? hoverLink.target : { id: hoverLink.target })}</p>
              </div>
              <p className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-700">點擊關係線查看連線資訊</p>
            </div>
            ) : null
          }
        >
        <ForceGraph2D
          ref={fgRef}
          graphData={filteredGraphData}
          nodeLabel="id"
          nodeVal={focusedNode ? 34 : filteredGraphData.nodes.length > 800 ? 1.5 : 34}
          linkDirectionalArrowLength={focusedNode || filteredGraphData.nodes.length <= 800 ? 5 : 0}
          linkDirectionalArrowRelPos={1}
          linkCurvature={0}
          onNodeHover={handleNodeHover}
          onNodeClick={handleNodeClick}
          onLinkHover={handleLinkHover}
          onLinkClick={handleLinkClick}
          onBackgroundClick={handleBackgroundClick}
          enableNodeDrag
          cooldownTicks={focusedNode ? 120 : 180}
          autoPauseRedraw
          nodeCanvasObject={(node, ctx, globalScale) => {
            const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
            const isDetail = detailNode && detailNode.id === node.id;
            const isFocused = focusedNode && focusedNode.id === node.id;
            const isHovered = hoverNode === node;
            const showNeo4jOverview = !focusedNode && filteredGraphData.nodes.length > 800 && globalScale < 1.0;

            if (showNeo4jOverview) {
              drawNeo4jOverviewNode(node, ctx, globalScale, {
                active: isDetail || isHovered,
                dimmed: !isHighlighted,
              });
              return;
            }

            const isLargeGraph = !focusedNode && filteredGraphData.nodes.length > 800;
            const baseR = isLargeGraph ? 8 : 28;
            const activeR = isLargeGraph ? 12 : 31;

            drawNeo4jNode(node, ctx, globalScale, {
              active: isDetail || isFocused || isHovered,
              dimmed: !isHighlighted,
              radius: baseR,
            });
            node.__nodeR = (isDetail || isFocused || isHovered) ? activeR : baseR;
          }}
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(node.x, node.y, focusedNode || filteredGraphData.nodes.length <= 800 ? 26 : 8, 0, 2 * Math.PI, false);
            ctx.fill();
          }}
          linkCanvasObjectMode={() => 'after'}
          linkCanvasObject={(link, ctx, globalScale) => {
            const isHighlighted = highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link));
            drawNeo4jLinkLabel(link, ctx, globalScale, { dimmed: !isHighlighted });
          }}
          linkColor={(link) => {
            const isOverview = !focusedNode && filteredGraphData.nodes.length > 800;
            if (isOverview) {
              return highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link)) ? '#58616d' : '#252a30';
            }
            return highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link)) ? '#9aa3af' : '#343b44';
          }}
          linkWidth={(link) => {
            const isOverview = !focusedNode && filteredGraphData.nodes.length > 800;
            if (isOverview) {
              return highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link)) ? 0.38 : 0.12;
            }
            return highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link)) ? 1.15 : 0.45;
          }}
          backgroundColor={NEO4J_GRAPH_BACKGROUND}
        />
        </Neo4jGraphShell>
      </div>

      {/* Detail Panel */}
      {detailNode && (
        <div className="w-full lg:w-80 bg-slate-900 border border-slate-700 rounded-lg p-4 h-auto lg:h-[800px] overflow-y-auto shrink-0 custom-scrollbar">
          <div className="flex justify-between items-start mb-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: TYPE_COLORS[detailNode.type] || TYPE_COLORS.default }} />
                <span className="text-xs text-slate-400 font-bold uppercase">{detailNode.type || 'Concept'}</span>
              </div>
              <h3 className="text-lg font-bold text-white">{detailNode.id}</h3>
            </div>
            <button 
              onClick={() => setDetailNode(null)}
              className="text-slate-500 hover:text-white"
            >✕</button>
          </div>

          <button
            onClick={() => handleFocusNode(detailNode)}
            className="w-full mb-4 py-2 px-3 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-bold rounded-lg transition-colors"
          >
            {focusedNode?.id === detailNode.id ? '取消聚焦' : '聚焦此節點（只顯示鄰居）'}
          </button>

          {(() => {
            const { incoming, outgoing } = getNodeNeighbors(detailNode.id);
            return (
              <>
                {outgoing.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                      向外連線 ({outgoing.length})
                    </h4>
                    <div className="space-y-1 max-h-60 overflow-y-auto custom-scrollbar">
                      {outgoing.map((o, i) => (
                        <button 
                          key={i}
                          onClick={() => {
                            const target = rawGraphData.nodes.find(n => n.id === o.node);
                            if (target) setDetailNode(target);
                          }}
                          className="w-full text-left p-2 bg-slate-800 hover:bg-slate-700 rounded text-sm flex items-center gap-2 group"
                        >
                          <span className="text-indigo-400 text-xs shrink-0">{o.rel}</span>
                          <span className="text-slate-300 group-hover:text-white truncate">→ {o.node}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {incoming.length > 0 && (
                  <div>
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                      向內連線 ({incoming.length})
                    </h4>
                    <div className="space-y-1 max-h-60 overflow-y-auto custom-scrollbar">
                      {incoming.map((o, i) => (
                        <button 
                          key={i}
                          onClick={() => {
                            const source = rawGraphData.nodes.find(n => n.id === o.node);
                            if (source) setDetailNode(source);
                          }}
                          className="w-full text-left p-2 bg-slate-800 hover:bg-slate-700 rounded text-sm flex items-center gap-2 group"
                        >
                          <span className="text-cyan-400 text-xs shrink-0">{o.rel}</span>
                          <span className="text-slate-300 group-hover:text-white truncate">← {o.node}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {incoming.length === 0 && outgoing.length === 0 && (
                  <p className="text-slate-500 text-sm">此節點沒有連線</p>
                )}
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
