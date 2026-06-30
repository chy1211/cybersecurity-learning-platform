import React, { useState, useEffect } from 'react';
import api from '../services/api';
import KnowledgeGraphViewer from '../components/KnowledgeGraphViewer';
import { buildChapterTitleMap, normalizeChapterName } from '../utils/chapterNameUtils';

const ChapterPage = () => {
  const [chapters, setChapters] = useState([]);
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [chapterUnits, setChapterUnits] = useState({});
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getChapters().then(data => {
      const rawUnits = data.map((item) => item.unit || item);
      const titleMap = buildChapterTitleMap(rawUnits);
      const grouped = new Map();
      const unitsMap = {};

      data.forEach((item) => {
        const rawUnit = item.unit || item;
        const displayName = normalizeChapterName(rawUnit, titleMap);
        if (!displayName) return;
        if (!grouped.has(displayName)) {
          grouped.set(displayName, { unit: displayName, node_count: 0 });
          unitsMap[displayName] = [];
        }
        grouped.get(displayName).node_count += item.node_count ?? 0;
        unitsMap[displayName].push(rawUnit);
      });

      const nextChapters = Array.from(grouped.values());
      nextChapters.sort((a, b) => a.unit.localeCompare(b.unit, 'zh-Hant'));

      setChapters(nextChapters);
      setChapterUnits(unitsMap);
      if (nextChapters.length > 0) {
        setSelectedChapter(nextChapters[0].unit);
      }
    });
  }, []);

  useEffect(() => {
    if (selectedChapter) {
      setLoading(true);
      const rawUnits = chapterUnits[selectedChapter] || [];
      if (rawUnits.length === 0) {
        setGraphData({ nodes: [], links: [] });
        setLoading(false);
        return;
      }
      const requests = Array.from(new Set(rawUnits)).map((unit) => api.getChapterGraph(unit));
      Promise.all(requests).then((results) => {
        const nodeMap = new Map();
        const linkMap = new Map();
        results.forEach((result) => {
          (result.nodes || []).forEach((node) => {
            if (!nodeMap.has(node.id)) {
              nodeMap.set(node.id, node);
            }
          });
          (result.links || []).forEach((link) => {
            const source = link.source?.id || link.source;
            const target = link.target?.id || link.target;
            const name = link.type || link.name || '';
            const key = `${source}|${name}|${target}`;
            if (!linkMap.has(key)) {
              linkMap.set(key, link);
            }
          });
        });
        setGraphData({
          nodes: Array.from(nodeMap.values()),
          links: Array.from(linkMap.values())
        });
        setLoading(false);
      });
    }
  }, [selectedChapter, chapterUnits]);

  return (
    <div className="max-w-[1600px] mx-auto px-4 py-8 h-full overflow-hidden flex flex-col">
      <h1 className="text-3xl font-bold mb-6 text-indigo-400 shrink-0">📖 章節導覽</h1>
      <p className="text-slate-400 mb-6 shrink-0">各章節包含的知識點，依據頻率與重要性排序。</p>
      
      <div className="flex flex-col md:flex-row gap-6 flex-1 min-h-0">
        <div className="w-full md:w-1/4 shrink-0 flex flex-col">
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4 flex-1 flex flex-col min-h-0">
            <h2 className="text-xl font-semibold mb-4 text-slate-200 shrink-0">章節列表</h2>
            <div className="space-y-2 overflow-y-auto pr-2 custom-scrollbar flex-1">
              {chapters.map(ch => {
                const unitName = ch.unit || ch;
                const nodeCount = ch.node_count;
                return (
                <button
                  key={unitName}
                  onClick={() => setSelectedChapter(unitName)}
                  className={`w-full text-left px-4 py-3 mb-1 rounded-md transition-colors flex justify-between items-center border border-transparent ${selectedChapter === unitName ? 'bg-indigo-600 text-white border-indigo-500 shadow-md' : 'hover:bg-slate-800 text-slate-400 hover:border-slate-700'}`}
                >
                  <span className="font-medium">{unitName}</span>
                  {nodeCount !== undefined && (
                    <span className={`text-xs px-2 py-1 rounded-full ${selectedChapter === unitName ? 'bg-indigo-500 text-white' : 'bg-slate-800 text-slate-500'}`}>
                      {nodeCount} 節點
                    </span>
                  )}
                </button>
              )})}
            </div>
          </div>
        </div>
        
        <div className="w-full md:w-3/4 min-w-0">
          <KnowledgeGraphViewer 
            graphData={graphData}
            title={selectedChapter ? `章節: ${selectedChapter}` : ''}
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
};

export default ChapterPage;
