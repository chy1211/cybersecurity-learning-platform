import test from 'node:test'
import assert from 'node:assert/strict'

import { getAnalysisSummary } from './analysisStatus.js'

test('marks zero coverage as unavailable', () => {
  const result = getAnalysisSummary({
    status: 'analysis_unavailable',
    community_node_count: 10,
    analysis_node_count: 0,
  })

  assert.equal(result.state, 'unavailable')
  assert.equal(result.isUnavailable, true)
  assert.equal(result.coverageText, '已分析 0 / 10 個節點（0%）')
})

test('marks incomplete coverage as partial', () => {
  const result = getAnalysisSummary({
    status: 'partial',
    community_node_count: 40,
    analysis_node_count: 30,
  })

  assert.equal(result.state, 'partial')
  assert.equal(result.isPartial, true)
  assert.equal(result.coveragePercent, 75)
})

test('marks full coverage as complete', () => {
  const result = getAnalysisSummary({
    status: 'ok',
    community_node_count: 12,
    analysis_node_count: 12,
  })

  assert.equal(result.state, 'complete')
  assert.equal(result.isComplete, true)
  assert.equal(result.coveragePercent, 100)
})
