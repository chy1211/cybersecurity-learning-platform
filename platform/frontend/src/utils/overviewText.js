const formatCount = (value) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null
  }
  return value.toLocaleString('en-US')
}

export function buildOverviewDescription({ nodeCount, communityCount, chapterCount }) {
  const formattedNodeCount = formatCount(nodeCount)
  const formattedCommunityCount = formatCount(communityCount)
  const formattedChapterCount = formatCount(chapterCount)

  if (!formattedNodeCount || !formattedCommunityCount || !formattedChapterCount) {
    return '本平台透過 Neo4j 知識圖譜整理資安概念、分群與章節模組，並以平台展示版 Graph RAG 輔助問答。結構排序僅供探索，不代表經驗證之先備次序或個人化學習成效。'
  }

  return `本平台以 Neo4j 管理 ${formattedNodeCount} 個資安知識節點、${formattedCommunityCount} 個分群與 ${formattedChapterCount} 個章節模組，並以平台展示版 Graph RAG 輔助問答。結構排序僅供探索，不代表經驗證之先備次序或個人化學習成效。`
}
