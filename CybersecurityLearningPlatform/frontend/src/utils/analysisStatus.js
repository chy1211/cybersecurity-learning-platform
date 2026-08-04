export function getAnalysisSummary(payload = {}) {
  const eligible = Number(payload?.community_node_count ?? 0)
  const analyzed = Number(payload?.analysis_node_count ?? 0)
  const coverage = eligible > 0 ? analyzed / eligible : 0

  let state = payload?.analysis_state
  if (!state) {
    if (payload?.status === 'analysis_unavailable' || eligible <= 0 || analyzed <= 0) {
      state = 'unavailable'
    } else if (payload?.status === 'partial' || analyzed < eligible) {
      state = 'partial'
    } else {
      state = 'complete'
    }
  }

  return {
    state,
    eligible,
    analyzed,
    coverage,
    coveragePercent: Math.round(coverage * 100),
    coverageText: `已分析 ${analyzed} / ${eligible} 個節點（${Math.round(coverage * 100)}%）`,
    isUnavailable: state === 'unavailable',
    isPartial: state === 'partial',
    isComplete: state === 'complete',
  }
}
