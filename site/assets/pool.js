import {
  apiGet,
  clear,
  el,
  formatBtcS,
  formatNumber,
  formatTime,
  initLayout,
  markUpdated,
  setState,
  setText,
  statusBadge,
} from './site.js'

initLayout()

const stateBox = document.getElementById('pool-state')
const ledgerBody = document.getElementById('fee-ledger-body')

function renderConfig(config, node, stratum) {
  const endpoint = config.stratum?.endpoint
  setText('pool-network', (config.network || '—').toUpperCase())
  setText('pool-fee', `${formatNumber(config.fee_percent, 2)}%`)
  setText('pool-method', config.reward_method || '—')
  setText('pool-payouts', config.auto_payouts ? 'Enabled' : 'Disabled')
  setText('pool-algorithm', config.algorithm || '—')
  setText('pool-method-detail', config.reward_method || '—')
  setText('pool-fee-detail', `${formatNumber(config.fee_percent, 2)}% of recorded coinbase value`)
  setText('pool-min-payout', `${formatNumber(config.min_payout_btcs, 8)} BTCS`)
  setText('pool-interval', `${formatNumber(config.payout_interval_seconds)} seconds`)
  setText('pool-maturity', `${formatNumber(config.maturity_confirmations)} confirmations`)
  setText('pool-auto', config.auto_payouts ? 'Enabled' : 'Disabled')
  setText('pool-node', node.connected ? (node.synced ? 'Connected and synced' : 'Connected') : 'Unavailable')
  setText('pool-height', formatNumber(node.blocks))
  setText('pool-ibd', node.initial_block_download ? 'Yes' : 'No')
  setText('pool-stratum', stratum.listening ? `Listening (${formatNumber(stratum.clients)} clients)` : 'Not listening')
  setText('pool-endpoint', endpoint || 'Not configured')
  setText('pool-api-version', config.api?.version || '—')
  setText('pool-rate-limit', `${formatNumber(config.api?.rate_limit_per_minute)} requests/minute`)
}

function renderLedger(rows) {
  clear(ledgerBody)
  if (!rows.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', 'No pool fees have been recorded yet.')
    td.colSpan = 5
    tr.append(td)
    ledgerBody.append(tr)
    return
  }
  for (const row of rows) {
    const tr = el('tr')
    tr.append(el('td', 'mono', row.block_height))
    const hash = el('td', 'hash mono', row.block_hash || '—')
    if (row.block_hash) hash.title = row.block_hash
    tr.append(hash)
    tr.append(el('td', 'mono', formatBtcS(row.fee_satoshi)))
    const status = el('td')
    status.append(statusBadge(row.status))
    tr.append(status)
    tr.append(el('td', null, formatTime(row.created_at)))
    ledgerBody.append(tr)
  }
}

async function load() {
  try {
    const [overview, ledger] = await Promise.all([
      apiGet('/pool/status'),
      apiGet('/pool/fee-ledger?limit=25'),
    ])
    renderConfig(overview.config || {}, overview.node || {}, overview.stratum || {})
    renderLedger(ledger.fee_ledger || [])
    setState(stateBox, 'ok', 'Configuration loaded', 'Values came from the public pool API, not static documentation.')
    markUpdated('pool-updated')
  } catch (error) {
    setState(stateBox, 'error', 'Configuration unavailable', `${error.message} No configuration values are being guessed.`)
    clear(ledgerBody)
    const tr = el('tr')
    const td = el('td', 'table-empty', 'Fee ledger unavailable.')
    td.colSpan = 5
    tr.append(td)
    ledgerBody.append(tr)
  }
}

load()
setInterval(load, 30000)
