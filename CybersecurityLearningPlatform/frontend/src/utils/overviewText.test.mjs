import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildOverviewDescription } from './overviewText.js'

test('builds overview description from live statistics', () => {
  const text = buildOverviewDescription({
    nodeCount: 2862,
    communityCount: 73,
    chapterCount: 25
  })

  assert.match(text, /2,862 個知識節點/)
  assert.match(text, /73 個學習社群/)
  assert.match(text, /25 個章節模組/)
  assert.doesNotMatch(text, /近 3,500/)
  assert.doesNotMatch(text, /111 個學習社群/)
})

test('uses neutral copy before statistics finish loading', () => {
  const text = buildOverviewDescription({
    nodeCount: null,
    communityCount: null,
    chapterCount: null
  })

  assert.match(text, /知識節點、學習社群與章節模組/)
  assert.doesNotMatch(text, /null|undefined|--/)
})
