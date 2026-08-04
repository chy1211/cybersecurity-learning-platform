import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildOverviewDescription } from './overviewText.js'

test('builds overview description from live statistics', () => {
  const text = buildOverviewDescription({
    nodeCount: 2763,
    communityCount: 87,
    chapterCount: 20
  })

  assert.match(text, /2,763 個資安知識節點/)
  assert.match(text, /87 個分群/)
  assert.match(text, /20 個章節模組/)
  assert.doesNotMatch(text, /近 3,500/)
  assert.doesNotMatch(text, /111 個學習社群/)
})

test('uses neutral copy before statistics finish loading', () => {
  const text = buildOverviewDescription({
    nodeCount: null,
    communityCount: null,
    chapterCount: null
  })

  assert.match(text, /資安概念、分群與章節模組/)
  assert.doesNotMatch(text, /null|undefined|--/)
})
