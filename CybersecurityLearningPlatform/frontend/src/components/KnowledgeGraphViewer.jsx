import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import LearningMode from './LearningMode';
import { buildChapterTitleMap, parseUnitItems, extractUnitLabel, summarizeChapterCounts } from '../utils/chapterNameUtils';
import {
  NEO4J_GRAPH_BACKGROUND,
  NEO4J_LABEL_COLORS,
  Neo4jGraphShell,
  createNeo4jCollisionForce,
  createNeo4jSpokeForce,
  drawNeo4jLinkLabel,
  drawNeo4jNode,
  getNeo4jNodeColor,
  getNeo4jNodeLabel,
} from './Neo4jGraphShell';

const getEndpointId = (endpoint) => (typeof endpoint === 'object' ? endpoint.id : endpoint);
const getLinkKey = (link) => `${getEndpointId(link.source)}--${link.name || ''}--${getEndpointId(link.target)}`;
const summarizeUnits = (value) => {
  const items = parseUnitItems(value);
  const rawLabels = items.map(extractUnitLabel).filter(Boolean);
  const titleMap = buildChapterTitleMap(rawLabels);
  return summarizeChapterCounts(items, titleMap);
};

const KnowledgeGraphViewer = ({ 
  graphData, 
  title, 
  subtitle,
  loading 
}) => {
  const fgRef = useRef();
  const containerRef = useRef();
  const needsInitialFit = useRef(true);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [hoverNode, setHoverNode] = useState(null);
  const [searchedNode, setSearchedNode] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeQuizNode, setActiveQuizNode] = useState(null);
  const hoverTopUnits = useMemo(() => (
    hoverNode ? summarizeUnits(hoverNode.top_3_units) : []
  ), [hoverNode]);

  // Responsive dimensions
  useEffect(() => {
    if (containerRef.current) {
      const resizeObserver = new ResizeObserver(entries => {
        for (let entry of entries) {
          setDimensions({
            width: entry.contentRect.width,
            height: entry.contentRect.height
          });
        }
      });
      resizeObserver.observe(containerRef.current);
      return () => resizeObserver.disconnect();
    }
  }, []);

  // Zoom to fit on data change — two-phase approach:
  // 1) Quick fit at 800ms for early visual feedback
  // 2) Final fit on onEngineStop to include all settled outlier nodes
  useEffect(() => {
    if (!loading && graphData && graphData.nodes.length > 0) {
      needsInitialFit.current = true;
      setTimeout(() => {
        if (fgRef.current) {
          fgRef.current.zoomToFit(500, 60);
        }
      }, 800);
    }
  }, [graphData, loading]);

  useEffect(() => {
    if (!fgRef.current || !graphData?.nodes?.length) return;
    const nodeCount = graphData.nodes.length;
    const charge = nodeCount > 100 ? -3600 : nodeCount > 60 ? -2900 : -2300;
    const linkDistance = nodeCount > 100 ? 330 : nodeCount > 60 ? 285 : 245;
    fgRef.current.d3Force('charge').strength(charge).distanceMax(1600);
    fgRef.current.d3Force('link').distance(linkDistance);
    fgRef.current.d3Force('center').strength(0.025);
    fgRef.current.d3Force('neo4jCollide', createNeo4jCollisionForce(30, 48));
    fgRef.current.d3Force('neo4jSpokes', createNeo4jSpokeForce(graphData.links, linkDistance, 0.075));
    fgRef.current.d3ReheatSimulation();
  }, [graphData]);

  const [highlightNodes, setHighlightNodes] = useState(new Set());
  const [highlightLinks, setHighlightLinks] = useState(new Set());

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.trim().toLowerCase();
    return (graphData?.nodes || [])
      .filter((node) => getNeo4jNodeLabel(node).toLowerCase().includes(q) || String(node.id || '').toLowerCase().includes(q))
      .slice(0, 10);
  }, [graphData, searchQuery]);

  const focusGraphNode = useCallback((node) => {
    if (!node) return;
    const nextNodes = new Set([node.id]);
    const nextLinks = new Set();
    (graphData?.links || []).forEach((link) => {
      const sourceId = getEndpointId(link.source);
      const targetId = getEndpointId(link.target);
      if (sourceId === node.id || targetId === node.id) {
        nextLinks.add(getLinkKey(link));
        nextNodes.add(sourceId);
        nextNodes.add(targetId);
      }
    });
    setSearchedNode(node);
    setHoverNode(node);
    setHighlightNodes(nextNodes);
    setHighlightLinks(nextLinks);
    setSearchQuery('');
    window.setTimeout(() => {
      if (fgRef.current && node.x !== undefined && node.y !== undefined) {
        fgRef.current.centerAt(node.x, node.y, 500);
        fgRef.current.zoom(2.4, 500);
      }
    }, 50);
  }, [graphData]);

  const handleNodeHover = useCallback(node => {
    const nextNodes = new Set();
    const nextLinks = new Set();
    if (node) {
      nextNodes.add(node.id);
      graphData.links.forEach(link => {
        const sourceId = getEndpointId(link.source);
        const targetId = getEndpointId(link.target);
        if (sourceId === node.id || targetId === node.id) {
          nextLinks.add(getLinkKey(link));
          nextNodes.add(sourceId);
          nextNodes.add(targetId);
        }
      });
    }
    setHighlightNodes(nextNodes);
    setHighlightLinks(nextLinks);
    setHoverNode(node || null);
    if (node) setHoverLink(null);
  }, [graphData]);

  const paintNode = useCallback((node, ctx, globalScale) => {
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
    const isHovered = hoverNode === node || searchedNode?.id === node.id;
    drawNeo4jNode(node, ctx, globalScale, {
      active: isHovered,
      dimmed: !isHighlighted,
      radius: 28,
    });
  }, [hoverNode, highlightNodes]);

  const paintLink = useCallback((link, ctx, globalScale) => {
    const isHighlighted = highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link));
    drawNeo4jLinkLabel(link, ctx, globalScale, { dimmed: !isHighlighted });
  }, [highlightLinks]);

  const handleNodeClick = useCallback(node => {
    // Open the quiz modal for this node
    setActiveQuizNode({
      id: node.id || node.name,
      data: { label: node.name }
    });
  }, []);

  const [hoverLink, setHoverLink] = useState(null);

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
    const sourceNode = graphData?.nodes?.find(n => n.id === sourceId);
    const targetNode = graphData?.nodes?.find(n => n.id === targetId);
    setHoverLink(link);
    setHoverNode(null);
    const nextNodes = new Set([sourceId, targetId]);
    const nextLinks = new Set([getLinkKey(link)]);
    setHighlightNodes(nextNodes);
    setHighlightLinks(nextLinks);
    // Center on the midpoint of the link
    if (fgRef.current && link.source?.x !== undefined && link.target?.x !== undefined) {
      const midX = (link.source.x + link.target.x) / 2;
      const midY = (link.source.y + link.target.y) / 2;
      fgRef.current.centerAt(midX, midY, 500);
    }
  }, [graphData]);

  return (
    <div ref={containerRef} className="w-full h-full">
      <Neo4jGraphShell
        title={title}
        subtitle={subtitle || `${graphData?.nodes?.length || 0} 個節點, ${graphData?.links?.length || 0} 條關聯`}
        graphData={graphData}
        loading={loading}
        onZoomIn={() => fgRef.current?.zoom(fgRef.current.zoom() * 1.5, 300)}
        onZoomOut={() => fgRef.current?.zoom(fgRef.current.zoom() / 1.5, 300)}
        onFit={() => fgRef.current?.zoomToFit(400, 60)}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        searchResults={searchResults}
        onSearchSelect={focusGraphNode}
        overlay={
        hoverNode ? (
        <div className="absolute top-14 left-4 z-10 bg-[#202428]/95 backdrop-blur-md p-4 rounded-md border shadow-xl max-w-sm pointer-events-none" style={{ borderColor: getNeo4jNodeColor(hoverNode) || NEO4J_LABEL_COLORS.default }}>
          <h4 className="text-base font-bold text-white mb-2 flex items-center gap-2">
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: getNeo4jNodeColor(hoverNode) }} />
            {getNeo4jNodeLabel(hoverNode)}
          </h4>
          <div className="space-y-1 text-sm">
            {hoverNode.unit_mentions !== undefined && (
              <p className="text-[#57C7E3]">本章出現: {hoverNode.unit_mentions} 次</p>
            )}
            {hoverNode.layer !== undefined && hoverNode.layer !== null && (
              <p className="text-[#6DCE9E]">拓撲層級: {hoverNode.layer}</p>
            )}
            {hoverNode.degree !== undefined && (
              <p className="text-[#EC7BEF]">Degree: {hoverNode.degree?.toFixed(2)}</p>
            )}
            {hoverNode.betweenness !== undefined && (
              <p className="text-[#BEDCF0]">Betweenness: {hoverNode.betweenness?.toFixed(2)}</p>
            )}
            {hoverNode.final_community !== undefined && (
              <p className="text-slate-300">社群 ID: {hoverNode.final_community}</p>
            )}
            {hoverTopUnits.length > 0 && (
              <p className="text-slate-400 text-xs mt-2">
                主要章節: {hoverTopUnits.map((unit) => `${unit.unit} (${unit.count})`).join(', ')}
              </p>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-700">點擊節點進入測驗</p>
        </div>
        ) : hoverLink ? (
        <div className="absolute top-14 left-4 z-10 bg-[#202428]/95 backdrop-blur-md p-4 rounded-md border border-[#9aa3af] shadow-xl max-w-sm pointer-events-none">
          <h4 className="text-base font-bold text-white mb-2 flex items-center gap-2">
            <span className="text-[#9aa3af]">─▶</span>
            {hoverLink.name || hoverLink.relationship || hoverLink.type || 'relationship'}
          </h4>
          <div className="space-y-1 text-sm">
            <p className="text-[#57C7E3]">來源: {getNeo4jNodeLabel(typeof hoverLink.source === 'object' ? hoverLink.source : { id: hoverLink.source })}</p>
            <p className="text-[#6DCE9E]">目標: {getNeo4jNodeLabel(typeof hoverLink.target === 'object' ? hoverLink.target : { id: hoverLink.target })}</p>
          </div>
          <p className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-700">點擊關係線查看連線資訊</p>
        </div>
        ) : null
        }
      >

      <ForceGraph2D
        ref={fgRef}
        width={dimensions.width}
        height={dimensions.height}
        graphData={graphData}
        nodeLabel="" // We use our custom tooltip
        nodeRelSize={6}
        nodeVal={34}
        nodeCanvasObject={paintNode}
        nodePointerAreaPaint={(node, color, ctx, globalScale) => {
          // Match the visual radius logic from drawNeo4jNode
          const visualRadius = Math.max(28, 5 / Math.max(globalScale, 0.001));
          const hitRadius = visualRadius + 4;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, hitRadius, 0, 2 * Math.PI, false);
          ctx.fill();
        }}
        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={1}
        linkColor={(link) => highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link)) ? '#9aa3af' : '#343b44'}
        linkWidth={(link) => highlightLinks.size === 0 || highlightLinks.has(getLinkKey(link)) ? 1.15 : 0.45}
        linkPointerAreaPaint={(link, color, ctx, globalScale) => {
          if (typeof link.source !== 'object' || typeof link.target !== 'object') return;
          const start = link.source;
          const end = link.target;
          const dx = end.x - start.x;
          const dy = end.y - start.y;
          const len = Math.sqrt(dx * dx + dy * dy);
          if (len === 0) return;
          const ux = dx / len;
          const uy = dy / len;
          const nx = -uy;
          const ny = ux;
          // Keep hit width constant at ~5px on screen regardless of zoom.
          // No nodeInset needed: react-force-graph paints node hit areas
          // ON TOP of link hit areas, so nodes always win near their center.
          const hitWidth = Math.max(0.5, 5 / globalScale);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.moveTo(start.x + nx * hitWidth, start.y + ny * hitWidth);
          ctx.lineTo(end.x + nx * hitWidth, end.y + ny * hitWidth);
          ctx.lineTo(end.x - nx * hitWidth, end.y - ny * hitWidth);
          ctx.lineTo(start.x - nx * hitWidth, start.y - ny * hitWidth);
          ctx.closePath();
          ctx.fill();
        }}
        linkCanvasObjectMode={() => 'after'}
        linkCanvasObject={paintLink}
        backgroundColor={NEO4J_GRAPH_BACKGROUND}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.4}
        cooldownTicks={160}
        autoPauseRedraw={false}
        onNodeHover={handleNodeHover}
        onNodeClick={handleNodeClick}
        onLinkHover={handleLinkHover}
        onLinkClick={handleLinkClick}
        enableNodeDrag
        onEngineStop={() => {
          if (fgRef.current && !hoverNode && needsInitialFit.current) {
            needsInitialFit.current = false;
            fgRef.current.zoomToFit(400, 80);
          }
        }}
      />
      </Neo4jGraphShell>

      {/* Render Quiz/Learning Mode overlay when a node is clicked */}
      {activeQuizNode && (
        <LearningMode
          chapter={activeQuizNode}
          onClose={() => setActiveQuizNode(null)}
          onComplete={() => setActiveQuizNode(null)}
        />
      )}
    </div>
  );
};

export default KnowledgeGraphViewer;
