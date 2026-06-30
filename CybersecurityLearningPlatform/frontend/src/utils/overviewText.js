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
    return '本平台透過 Neo4j 知識圖譜建構資安知識體系，利用 Leiden 社群偵測演算法整理知識節點、學習社群與章節模組，搭配拓撲分層與 Graph RAG 智慧導師，為你量身打造個人化的學習路徑。'
  }

  return `本平台透過 Neo4j 知識圖譜建構資安知識體系，利用 Leiden 社群偵測演算法將 ${formattedNodeCount} 個知識節點分為 ${formattedCommunityCount} 個學習社群，搭配 ${formattedChapterCount} 個章節模組、拓撲分層與 Graph RAG 智慧導師，為你量身打造個人化的學習路徑。`
}
