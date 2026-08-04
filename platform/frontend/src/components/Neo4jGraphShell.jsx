import React, { useEffect, useRef, useState } from 'react';

export const NEO4J_LABEL_COLORS = {
  Concept: '#F16667',
  Technology: '#A5ABB6',
  Protocol: '#57C7E3',
  Attack: '#FFD700',
  Threat: '#F79767',
  Asset: '#4C8EDA',
  Control: '#6DCE9E',
  Role: '#D33115',
  Standard: '#8DCC93',
  app: '#B4E04B',
  attack: '#D4B5D9',
  attacker: '#92E8E8',
  data: '#00CC99',
  feature: '#F5A0F2',
  function: '#91F5CE',
  policy: '#E3B505',
  principle: '#B9D90D',
  risk: '#BEDCF0',
  securityTeam: '#FFAD66',
  system: '#E0A6D1',
  technique: '#B586D6',
  tool: '#A7F3B5',
  user: '#EBD66B',
  vulnerability: '#EC7BEF',
  default: '#A5ABB6',
};

const GRAPH_BG = '#1b1f23';
const LINK_COLOR = '#9aa3af';

export function getNeo4jNodeType(node) {
  if (!node) return 'default';
  if (node.type) return node.type;
  if (Array.isArray(node.labels) && node.labels.length > 0) return node.labels[0];
  if (node.data?.status) return node.data.status;
  return 'Concept';
}

export function getNeo4jNodeColor(node) {
  const type = getNeo4jNodeType(node);
  return NEO4J_LABEL_COLORS[type] || NEO4J_LABEL_COLORS.default;
}

export function getNeo4jNodeLabel(node) {
  return node?.name || node?.label || node?.id || node?.data?.label || '';
}

export function createNeo4jCollisionForce(radius = 42, padding = 16) {
  let nodes = [];
  const force = (alpha) => {
    for (let i = 0; i < nodes.length; i += 1) {
      const a = nodes[i];
      if (a.x === undefined || a.y === undefined) continue;
      for (let j = i + 1; j < nodes.length; j += 1) {
        const b = nodes[j];
        if (b.x === undefined || b.y === undefined) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let distance = Math.sqrt(dx * dx + dy * dy);
        const minDistance = radius * 2 + padding;
        if (distance === 0) {
          dx = (i % 2 === 0 ? 1 : -1) * 0.01;
          dy = (j % 2 === 0 ? 1 : -1) * 0.01;
          distance = Math.sqrt(dx * dx + dy * dy);
        }
        if (distance < minDistance) {
          const push = ((minDistance - distance) / distance) * alpha * 0.55;
          const x = dx * push;
          const y = dy * push;
          b.vx = (b.vx || 0) + x;
          b.vy = (b.vy || 0) + y;
          a.vx = (a.vx || 0) - x;
          a.vy = (a.vy || 0) - y;
        }
      }
    }
  };
  force.initialize = (nextNodes) => {
    nodes = nextNodes || [];
  };
  return force;
}

export function createNeo4jSpokeForce(links, distance = 220, strength = 0.05) {
  let nodes = [];
  let nodeById = new Map();
  let adjacency = [];

  const endpointId = (endpoint) => (typeof endpoint === 'object' ? endpoint.id : endpoint);

  const rebuild = () => {
    const neighborsById = new Map();
    (links || []).forEach((link) => {
      const source = endpointId(link.source);
      const target = endpointId(link.target);
      if (!source || !target || source === target) return;
      if (!neighborsById.has(source)) neighborsById.set(source, new Set());
      if (!neighborsById.has(target)) neighborsById.set(target, new Set());
      neighborsById.get(source).add(target);
      neighborsById.get(target).add(source);
    });
    adjacency = Array.from(neighborsById.entries())
      .map(([id, neighborIds]) => ({
        center: nodeById.get(id),
        neighbors: Array.from(neighborIds).sort().map((neighborId) => nodeById.get(neighborId)).filter(Boolean),
      }))
      .filter((entry) => entry.center && entry.neighbors.length > 2);
  };

  const force = (alpha) => {
    adjacency.forEach(({ center, neighbors }) => {
      if (center.x === undefined || center.y === undefined) return;
      const count = neighbors.length;
      neighbors.forEach((neighbor, index) => {
        if (neighbor.x === undefined || neighbor.y === undefined) return;
        const angle = (Math.PI * 2 * index) / count;
        const targetX = center.x + Math.cos(angle) * distance;
        const targetY = center.y + Math.sin(angle) * distance;
        neighbor.vx = (neighbor.vx || 0) + (targetX - neighbor.x) * strength * alpha;
        neighbor.vy = (neighbor.vy || 0) + (targetY - neighbor.y) * strength * alpha;
      });
    });
  };

  force.initialize = (nextNodes) => {
    nodes = nextNodes || [];
    nodeById = new Map(nodes.map((node) => [node.id, node]));
    rebuild();
  };

  return force;
}

export function collectGraphStats(graphData) {
  const nodeStats = new Map();
  const relStats = new Map();

  (graphData?.nodes || []).forEach((node) => {
    const key = getNeo4jNodeType(node);
    nodeStats.set(key, (nodeStats.get(key) || 0) + 1);
  });

  (graphData?.links || []).forEach((link) => {
    const key = link.name || link.relationship || link.type || 'relationship';
    relStats.set(key, (relStats.get(key) || 0) + 1);
  });

  return {
    nodeStats: Array.from(nodeStats.entries()).sort(([a], [b]) => a.localeCompare(b)),
    relStats: Array.from(relStats.entries()).sort(([a], [b]) => a.localeCompare(b)),
  };
}

function Pill({ label, count, color, shape = 'rounded' }) {
  return (
    <span
      className={`inline-flex items-center h-6 px-2.5 text-xs font-bold text-[#111827] ${shape === 'rel' ? 'neo4j-rel-pill' : 'rounded-full'}`}
      style={{ backgroundColor: color }}
      title={`${label} (${count})`}
    >
      {label} ({count})
    </span>
  );
}

export function Neo4jResultsOverview({ graphData, collapsed, onToggle }) {
  const { nodeStats, relStats } = collectGraphStats(graphData);
  const nodeCount = graphData?.nodes?.length || 0;
  const linkCount = graphData?.links?.length || 0;

  if (collapsed) {
    return (
      <aside className="neo4j-results-overview w-11 shrink-0 border-l border-[#3c424a] bg-[#202428] flex flex-col items-center py-3">
        <button
          type="button"
          onClick={onToggle}
          className="w-8 h-8 rounded border border-[#4a515a] text-[#d8dee6] hover:bg-[#343b44] hover:text-white"
          title="Expand Results overview"
        >
          ‹
        </button>
        <div className="mt-4 text-[11px] font-bold text-[#f4f7fb] [writing-mode:vertical-rl] rotate-180 tracking-wide">
          Results overview
        </div>
      </aside>
    );
  }

  return (
    <aside className="neo4j-results-overview w-full lg:w-[386px] shrink-0 border-l border-[#3c424a] bg-[#202428] px-4 py-4 overflow-y-auto custom-scrollbar">
      <div className="flex items-center justify-between mb-5">
        <h4 className="text-sm font-bold text-[#f4f7fb]">Results overview</h4>
        <button
          type="button"
          onClick={onToggle}
          className="w-8 h-8 rounded border border-transparent text-[#9aa3af] hover:border-[#4a515a] hover:bg-[#343b44] hover:text-white"
          title="Collapse Results overview"
        >
          ›
        </button>
      </div>

      <div className="mb-5">
        <div className="text-sm font-semibold text-[#f4f7fb] mb-2">Nodes ({nodeCount})</div>
        <div className="flex flex-wrap gap-2">
          <Pill label="*" count={nodeCount} color="#c59af7" />
          {nodeStats.map(([label, count]) => (
            <Pill key={label} label={label} count={count} color={NEO4J_LABEL_COLORS[label] || NEO4J_LABEL_COLORS.default} />
          ))}
        </div>
      </div>

      <div>
        <div className="text-sm font-semibold text-[#f4f7fb] mb-2">Relationships ({linkCount})</div>
        <div className="flex flex-wrap gap-2">
          <Pill label="*" count={linkCount} color="#f2f4f8" shape="rel" />
          {relStats.map(([label, count]) => (
            <Pill key={label} label={label} count={count} color="#f2f4f8" shape="rel" />
          ))}
        </div>
      </div>
    </aside>
  );
}

export function Neo4jGraphToolbar({ onZoomIn, onZoomOut, onFit, isFullScreen, onToggleFullScreen }) {
  return (
    <div className="absolute bottom-4 right-4 z-20 pointer-events-none">
      <div className="neo4j-graph-toolbar pointer-events-auto flex items-center rounded-md border border-[#4a515a] bg-[#242a30]/95 shadow-xl">
        <button type="button" onClick={onZoomIn} className="neo4j-tool-button" title="Zoom in">⌕+</button>
        <button type="button" onClick={onZoomOut} className="neo4j-tool-button border-l border-[#4a515a]" title="Zoom out">⌕−</button>
        <button type="button" onClick={onFit} className="neo4j-tool-button border-l border-[#4a515a]" title="Zoom to fit">▣</button>
        <button 
          type="button" 
          onClick={onToggleFullScreen} 
          className="neo4j-tool-button border-l border-[#4a515a] text-lg" 
          title={isFullScreen ? "Exit Full Screen" : "Full Screen"}
        >
          {isFullScreen ? '⛶' : '⛶'}
        </button>
      </div>
    </div>
  );
}

export function Neo4jGraphShell({
  title,
  subtitle,
  queryText,
  graphData,
  loading,
  children,
  onZoomIn,
  onZoomOut,
  onFit,
  overlay,
  searchQuery,
  onSearchQueryChange,
  searchResults = [],
  onSearchSelect,
}) {
  const graphPaneRef = useRef(null);
  const [graphSize, setGraphSize] = useState({ width: 320, height: 560 });
  const [overviewCollapsed, setOverviewCollapsed] = useState(true);
  const [isFullScreen, setIsFullScreen] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isFullScreen) {
        setIsFullScreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullScreen]);

  const toggleFullScreen = () => {
    setIsFullScreen(!isFullScreen);
  };

  useEffect(() => {
    if (!graphPaneRef.current) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      setGraphSize({
        width: Math.max(320, Math.floor(entry.contentRect.width)),
        height: Math.max(320, Math.floor(entry.contentRect.height)),
      });
    });
    observer.observe(graphPaneRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div className={`neo4j-graph-shell w-full min-w-0 h-full min-h-[560px] rounded-md border border-[#3c424a] bg-[#1f2328] overflow-hidden flex flex-col ${isFullScreen ? 'fixed inset-0 z-[1000] rounded-none' : ''}`}>
      <div className="h-10 shrink-0 border-b border-[#3c424a] bg-[#202428] flex items-center justify-between px-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-[#f4f7fb] truncate">{title}</div>
          {subtitle && <div className="text-[10px] text-[#9aa3af] truncate">{subtitle}</div>}
        </div>
        {isFullScreen && (
          <button 
            onClick={() => setIsFullScreen(false)}
            className="text-[#9aa3af] hover:text-white text-xs px-2 py-1 rounded hover:bg-[#343b44] border border-[#3c424a]"
          >
            退出全螢幕 (Esc)
          </button>
        )}
      </div>

      {queryText && (
        <div className="neo4j-query-editor h-[98px] shrink-0 border-b border-[#3c424a] bg-[#202428] px-4 py-2 font-mono text-sm leading-5 text-[#f4f7fb]">
          {queryText.split('\n').map((line, index) => (
            <div key={`${line}-${index}`} className="flex gap-3">
              <span className="w-4 text-right text-[#6b7280] select-none">{index + 1}</span>
              <span>
                {line.startsWith('MATCH') ? <span className="text-[#ffb000]">MATCH</span> : null}
                {line.startsWith('RETURN') ? <span className="text-[#ffb000]">RETURN</span> : null}
                <span>{line.replace(/^(MATCH|RETURN)/, '')}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        <div ref={graphPaneRef} className="relative flex-1 min-w-0 bg-[#1b1f23] overflow-hidden">
          <span className="sr-only">Graph visualization</span>
          {onSearchQueryChange && (
            <div className="absolute top-2 left-2 z-20 w-48 pointer-events-none">
              <input
                type="text"
                value={searchQuery || ''}
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder="搜尋節點..."
                className="pointer-events-auto w-full h-8 rounded-md border border-[#45505c] bg-[#202428]/90 px-3 text-xs text-[#f4f7fb] placeholder-[#7f8995] outline-none focus:border-[#57C7E3]"
              />
              {searchResults.length > 0 && (
                <div className="pointer-events-auto mt-1 max-h-56 overflow-y-auto rounded-md border border-[#45505c] bg-[#202428] shadow-xl custom-scrollbar">
                  {searchResults.map((node) => (
                    <button
                      key={node.id || getNeo4jNodeLabel(node)}
                      type="button"
                      onClick={() => onSearchSelect?.(node)}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs text-[#d8dee6] hover:bg-[#343b44]"
                    >
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: getNeo4jNodeColor(node) }} />
                      <span className="truncate">{getNeo4jNodeLabel(node)}</span>
                      <span className="ml-auto text-[#9aa3af]">{getNeo4jNodeType(node)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {loading && (
            <div className="absolute inset-0 z-30 bg-[#1b1f23]/80 flex items-center justify-center backdrop-blur-sm">
              <div className="h-11 w-11 rounded-full border-2 border-[#57c7e3] border-t-transparent animate-spin" />
            </div>
          )}
          {React.isValidElement(children)
            ? React.cloneElement(children, { width: graphSize.width, height: graphSize.height })
            : children}
          {overlay}
          <Neo4jGraphToolbar 
            onZoomIn={onZoomIn} 
            onZoomOut={onZoomOut} 
            onFit={onFit} 
            isFullScreen={isFullScreen}
            onToggleFullScreen={toggleFullScreen}
          />
        </div>
        <Neo4jResultsOverview
          graphData={graphData}
          collapsed={overviewCollapsed}
          onToggle={() => setOverviewCollapsed((value) => !value)}
        />
      </div>


    </div>
  );
}

export function drawNeo4jNode(node, ctx, globalScale, options = {}) {
  const label = getNeo4jNodeLabel(node);
  const color = getNeo4jNodeColor(node);
  const isDimmed = options.dimmed;
  const isActive = options.active;
  const baseRadius = options.radius || 24;
  const minScreenRadius = options.minScreenRadius || 5;
  const radius = Math.max(baseRadius, minScreenRadius / Math.max(globalScale, 0.001)) * (isActive ? 1.12 : 1);
  const fontSize = (10 + 2 * Math.sqrt(globalScale)) / globalScale; // Grows gently from 12px to ~18px on screen
  const maxChars = radius > 26 ? 12 : 8;

  ctx.save();
  ctx.globalAlpha = isDimmed ? 0.16 : 1;
  if (isActive) {
    ctx.shadowColor = color;
    ctx.shadowBlur = 18;
  }
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 1.6 / globalScale;
  ctx.strokeStyle = '#111827';
  ctx.stroke();

  const screenRadius = radius * globalScale;
  if (screenRadius > 14) {
    const displayLabel = label.length > maxChars ? `${label.slice(0, maxChars - 1)}...` : label;
    ctx.font = `700 ${fontSize}px Arial, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#111827';
    const words = displayLabel.split(/\s+/);
    if (displayLabel.length > 7 && words.length === 1) {
      ctx.fillText(displayLabel.slice(0, Math.ceil(displayLabel.length / 2)), node.x, node.y - fontSize * 0.45);
      ctx.fillText(displayLabel.slice(Math.ceil(displayLabel.length / 2)), node.x, node.y + fontSize * 0.75);
    } else {
      ctx.fillText(displayLabel, node.x, node.y);
    }
  }
  ctx.restore();
}

export function drawNeo4jLinkLabel(link, ctx, globalScale, options = {}) {
  const label = link.name || link.relationship || link.type;
  if (!label || globalScale < 2.5 || typeof link.source !== 'object' || typeof link.target !== 'object') return;

  const start = link.source;
  const end = link.target;
  const midX = start.x + (end.x - start.x) / 2;
  const midY = start.y + (end.y - start.y) / 2;
  const angle = Math.atan2(end.y - start.y, end.x - start.x);
  const fontSize = 9 / globalScale; // Keeps text at roughly 9px on the screen, preventing it from getting huge when zoomed in.

  ctx.save();
  ctx.globalAlpha = options.dimmed ? 0.15 : 0.95;
  ctx.translate(midX, midY);
  ctx.rotate(angle > Math.PI / 2 || angle < -Math.PI / 2 ? angle + Math.PI : angle);
  ctx.font = `700 ${fontSize}px Arial, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = LINK_COLOR;
  ctx.fillText(label, 0, -3 / globalScale);
  ctx.restore();
}

export const NEO4J_GRAPH_BACKGROUND = GRAPH_BG;
export const NEO4J_LINK_COLOR = LINK_COLOR;
