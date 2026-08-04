export const MIN_DISPLAY_COMMUNITY_SIZE = 10

export function getCommunityNodeCount(community) {
  const parsedSize = Number(community?.size)
  if (Number.isFinite(parsedSize)) {
    return parsedSize
  }

  if (Array.isArray(community?.nodes)) {
    return community.nodes.length
  }

  return 0
}

export function filterDisplayCommunities(communities, minSize = MIN_DISPLAY_COMMUNITY_SIZE) {
  return (communities || []).filter((community) => getCommunityNodeCount(community) >= minSize)
}

export function filterSearchResultsByVisibleCommunities(results, visibleCommunities) {
  const visibleIds = new Set((visibleCommunities || []).map((community) => String(community.community)))
  return (results || []).filter((result) => visibleIds.has(String(result.community)))
}
