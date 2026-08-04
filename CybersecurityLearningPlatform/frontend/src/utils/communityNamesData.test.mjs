import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const payload = JSON.parse(
  fs.readFileSync(new URL('../data/community-names-20260715.json', import.meta.url), 'utf-8'),
)

const correctedNames = {
  1: '資料保護、存取治理與隱私合規',
  2: '個人資料權利、法規遵循與釣魚防護',
  5: 'SIEM、SOC 與安全日誌監控',
  6: '物聯網、5G 與聯網裝置安全',
  7: '電子郵件安全、惡意程式與身分驗證',
  8: '存取控制、密碼政策與金鑰防護',
  10: '備份容錯、安全開發與技術控制',
  11: '資安事件處理、回應與威脅偵測',
  12: '營運持續、災難復原與風險降低',
  13: 'Web 應用與資料庫攻擊防護',
  14: '系統弱點評估、滲透測試與程式碼掃描',
  15: '資安稽核、惡意程式與備份防護',
  16: '物聯網、大數據與網路協定架構',
  18: '資訊資產盤點、分類與風險分析',
  25: '電子商務、電子簽章與區塊鏈信任',
  28: '行動通訊、4G LTE 與裝置安全',
  32: 'Linux 系統、檔案權限與安全日誌',
  41: '實體安全監控、警報與入侵偵測',
  42: '資安事件通報與個資蒐集告知',
  66: 'FIPS 140 密碼模組驗證與實驗室測試',
}

test('major community naming file covers 40 communities', () => {
  assert.equal(Object.keys(payload.names).length, 40)
})

test('major community naming file has no pending placeholders or bare chapter/module codes', () => {
  const values = Object.values(payload.names)
  const pending = values.filter((name) => name.includes('待人工確認'))
  const bareCodes = values.filter((name) => /^(CH|MOD)\d+$/i.test(name.trim()))

  assert.deepEqual(pending, [])
  assert.deepEqual(bareCodes, [])
})


test('major community names match the complete 2026-07-16 live-graph review', () => {
  assert.equal(payload.version, '2026-07-16')
  assert.equal(payload.reviewed_community_count, 40)

  for (const [communityId, expectedName] of Object.entries(correctedNames)) {
    assert.equal(payload.names[communityId], expectedName, `community ${communityId}`)
  }
})
