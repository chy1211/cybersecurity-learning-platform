import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  MIN_DISPLAY_COMMUNITY_SIZE,
  filterDisplayCommunities,
  filterSearchResultsByVisibleCommunities
} from './communityFilters.js'

test('filters display communities to node counts greater than or equal to the threshold', () => {
  const communities = [
    { community: 16, size: 148 },
    { community: 37, size: 10 },
    { community: 34, size: 9 },
    { community: 69, size: 1 }
  ]

  assert.equal(MIN_DISPLAY_COMMUNITY_SIZE, 10)
  assert.deepEqual(
    filterDisplayCommunities(communities).map((community) => community.community),
    [16, 37]
  )
})

test('falls back to node array length when size is missing', () => {
  const communities = [
    { community: 1, nodes: Array.from({ length: 10 }, (_, index) => ({ name: `n${index}` })) },
    { community: 2, nodes: Array.from({ length: 9 }, (_, index) => ({ name: `n${index}` })) }
  ]

  assert.deepEqual(
    filterDisplayCommunities(communities).map((community) => community.community),
    [1]
  )
})

test('filters search results to visible communities', () => {
  const visibleCommunities = [
    { community: 16, size: 148 },
    { community: 37, size: 10 }
  ]
  const results = [
    { name: 'A', community: 16 },
    { name: 'B', community: '37' },
    { name: 'C', community: 34 }
  ]

  assert.deepEqual(
    filterSearchResultsByVisibleCommunities(results, visibleCommunities).map((result) => result.name),
    ['A', 'B']
  )
})
