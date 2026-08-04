import React, { useState, useEffect } from 'react';
import api from '../services/api';
import KnowledgeGraphViewer from '../components/KnowledgeGraphViewer';
import { getCommunityDisplayName } from '../services/communityNames';
import { filterDisplayCommunities } from '../utils/communityFilters';

const TopicPage = () => {
  const [communities, setCommunities] = useState([]);
  const [selectedCommunity, setSelectedCommunity] = useState(null);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getCommunities().then(data => {
      const visibleCommunities = filterDisplayCommunities(data);
      setCommunities(visibleCommunities);
      if (visibleCommunities.length > 0) {
        setSelectedCommunity(visibleCommunities[0].community);
      } else {
        setSelectedCommunity(null);
      }
    });
  }, []);

  useEffect(() => {
    if (selectedCommunity !== null) {
      setLoading(true);
      api.getCommunityGraph(selectedCommunity).then(data => {
        setGraphData(data);
        setLoading(false);
      });
    }
  }, [selectedCommunity]);

  return (
    <div className="max-w-[1600px] mx-auto px-4 py-8 h-full overflow-hidden flex flex-col">
      <h1 className="text-3xl font-bold mb-6 text-fuchsia-400 shrink-0">🧠 主題模組 (Community Knowledge Graph)</h1>
      <p className="text-slate-400 mb-6 shrink-0">基於圖論社群偵測所發現的潛在主題分類，以 Neo4j 風格的力導向圖視覺化呈現關聯性。</p>
      
      <div className="flex flex-col md:flex-row gap-6 flex-1 min-h-0">
        {/* Left Sidebar */}
        <div className="w-full md:w-1/4 shrink-0 flex flex-col">
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4 flex-1 flex flex-col min-h-0">
            <h2 className="text-xl font-semibold mb-4 text-slate-200 shrink-0">社群列表</h2>
            <div className="space-y-1 overflow-y-auto pr-2 custom-scrollbar flex-1">
              {communities.map(comm => (
                <button
                  key={comm.community}
                  onClick={() => setSelectedCommunity(comm.community)}
                  className={`w-full text-left px-3 py-2.5 rounded-md transition-colors flex flex-col gap-0.5 ${selectedCommunity === comm.community ? 'bg-fuchsia-600 text-white' : 'hover:bg-slate-800 text-slate-400'}`}
                >
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium truncate">{getCommunityDisplayName(comm.community)}</span>
                    <span className="text-xs bg-black/20 px-2 py-0.5 rounded-full shrink-0 ml-2">{comm.size} 節點</span>
                  </div>
                  <span className={`text-[10px] ${selectedCommunity === comm.community ? 'text-fuchsia-200' : 'text-slate-600'}`}>社群 ID #{comm.community}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
        
        {/* Right Graph View */}
        <div className="w-full md:w-3/4 min-w-0">
          <KnowledgeGraphViewer 
            graphData={graphData}
            title={selectedCommunity !== null ? getCommunityDisplayName(selectedCommunity) : ''}
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
};

export default TopicPage;
