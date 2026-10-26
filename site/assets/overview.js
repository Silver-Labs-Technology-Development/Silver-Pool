import {
  apiGet,
  clear,
  el,
  formatBtcS,
  formatHashrate,
  formatNumber,
  formatTime,
  initLayout,
  markUpdated,
  setState,
  setText,
  shortHash,
  startPolling,
  statusBadge,
} from './site.js'

initLayout()

const stateBox = document.getElementById('overview-state')
let lastSuccess = null
let firstLoad = true

function setDot(id, kind) {
  const node = document.getElementById(id)
  if (node) node.className = `dot dot-${kind}`
}

function setService(id, kind, text) {
  setDot(`overview-${id}-dot`, kind)
  setText(`overview-${id}-text`, text)
}

function endpointText(config) {
  return config?.stratum?.endpoint || 'Not configured'
}

function renderConfig(config) {
  const list = document.getElementById('pool-config-list')
  if (!list || !config) return
  clear(list)
  const rows = [
    ['Algorithm', config.algorithm || '—'],
    ['Fee', `${formatNumber(config.fee_percent, 2)}%`],
    ['Reward method', config.reward_method || '—'],
    ['Minimum payout', `${formatNumber(config.min_payout_btcs, 8)} BTCS`],
    ['Coinbase maturity', `${formatNumber(config.maturity_confirmations)} blocks`],
    ['Automatic payouts', config.auto_payouts ? 'Enabled' : 'Disabled'],
  ]
  for (const [label, value] of rows) {
    const row = el('div', 'row')
    row.append(el('dt', null, label), el('dd', null, value))
    list.append(row)
  }
}

function blockRow(block) {
  const tr = el('tr')
  tr.append(el('td', 'mono', block.height))
  const hashCell = el('td', 'hash mono', shortHash(block.hash, 9))
  hashCell.title = block.hash
  tr.append(hashCell)
  const minerCell = el('td')
  if (block.miner) {
    const link = el('a', null, block.miner)
    link.href = `miner/?miner=${encodeURIComponent(block.miner)}`
    minerCell.append(link)
  } else {
    minerCell.textContent = '—'
  }
  tr.append(minerCell)
  tr.append(el('td', null, formatBtcS(block.net_reward_satoshi)))
  const status = el('td')
  status.append(statusBadge(block.status))
  tr.append(status)
  tr.append(el('td', null, formatTime(block.found_at)))
  return tr
}

function shareRow(share) {
  const tr = el('tr')
  tr.append(el('td', null, share.miner || '—'))
  tr.append(el('td', null, share.worker || '—'))
  tr.append(el('td', 'mono', share.job_id || '—'))
  tr.append(el('td', 'mono', formatNumber(share.difficulty, 4)))
  const result = el('td')
  if (share.accepted) result.append(statusBadge('accepted'))
  else if (share.stale) result.append(statusBadge('orphaned'))
  else result.append(statusBadge('rejected'))
  tr.append(result)
  tr.append(el('td', null, share.reject_reason || (share.stale ? 'stale' : '—')))
  tr.append(el('td', null, formatTime(share.created_at)))
  return tr
}

function renderTables(data) {
  const blocksBody = document.getElementById('recent-blocks-body')
  const sharesBody = document.getElementById('recent-shares-body')
  clear(blocksBody)
  clear(sharesBody)
  if (!data.recent_blocks?.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', 'No blocks have been found by this pool yet.')
    td.colSpan = 6
    tr.append(td)
    blocksBody.append(tr)
  } else {
    data.recent_blocks.forEach((block) => blocksBody.append(blockRow(block)))
  }
  if (!data.recent_shares?.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', 'No share submissions have been recorded yet.')
    td.colSpan = 7
    tr.append(td)
    sharesBody.append(tr)
  } else {
    data.recent_shares.forEach((share) => sharesBody.append(shareRow(share)))
  }
}

function render(data) {
  const pool = data.pool || {}
  const node = data.node || {}
  const stratum = data.stratum || {}
  const config = data.config || {}
  const hashrate = formatHashrate(data.hashrate?.estimate_24h)

  const nodeKind = !node.connected
    ? 'error'
    : node.initial_block_download
      ? 'offline'
      : node.synced
        ? 'online'
        : 'offline'
  const stratumKind = stratum.listening ? 'online' : 'offline'
  const poolReady = nodeKind === 'online' && stratumKind === 'online'

  setDot('hero-dot', poolReady ? 'online' : 'offline')
  setText(
    'hero-status-text',
    !node.connected
      ? 'Pool API online, but the BTCS node is unavailable. Live mining values cannot be trusted.'
      : node.initial_block_download
        ? `BTCS node is in initial block download (${(Number(node.verification_progress || 0) * 100).toFixed(2)}%).`
        : poolReady
          ? 'Pool API online · BTCS node synced · Stratum accepting connections.'
          : 'Pool API online · Stratum is not currently accepting connections.',
  )
  setText('hero-network', (config.network || node.network || '—').toUpperCase())
  setText('hero-endpoint', endpointText(config))
  setText(
    'hero-node',
    node.connected ? `Synced · height ${formatNumber(node.blocks)}` : 'Unavailable',
  )

  setText('stat-miners', formatNumber(pool.total_miners))
  setText('stat-active', formatNumber(pool.active_miners_24h))
  setText('stat-accepted', formatNumber(pool.accepted_shares))
  setText('stat-rejected', `${formatNumber(pool.rejected_shares)} rejected`)
  setText('stat-blocks', formatNumber(pool.total_blocks))
  setText(
    'stat-blocks-detail',
    `${formatNumber(pool.mature_blocks)} mature · ${formatNumber(pool.immature_blocks)} immature`,
  )
  setText('stat-hashrate', `${hashrate.value} ${hashrate.unit}`)
  setText('stat-reward', config.reward_method || '—')
  setText('stat-fee', `${formatNumber(config.fee_percent, 2)}% pool fee`)
  setText('stat-height', formatNumber(node.blocks))
  setText(
    'stat-sync',
    node.connected
      ? node.initial_block_download
        ? `Syncing · ${(Number(node.verification_progress || 0) * 100).toFixed(2)}%`
        : node.synced
          ? 'Synced with the BTCS node'
          : 'Connected, not synced'
      : 'Node unavailable',
  )
  setText('stat-round', data.round ? `#${data.round.height}` : '—')
  setText(
    'stat-round-detail',
    data.round
      ? `${formatNumber(data.round.total_shares)} shares · ${formatNumber(data.round.total_difficulty, 2)} difficulty`
      : 'Waiting for a job',
  )

  setService('api', 'online', 'Responding')
  setService('node', nodeKind, node.connected ? (node.synced ? 'Synced' : 'Not synced') : 'Unavailable')
  setService('stratum', stratumKind, stratum.listening ? `${formatNumber(stratum.clients)} clients` : 'Not listening')
  setService('db', 'online', 'Writable')

  const configRows = [
    ['Algorithm', config.algorithm || '—'],
    ['Fee', `${formatNumber(config.fee_percent, 2)}%`],
    ['Minimum payout', `${formatNumber(config.min_payout_btcs, 8)} BTCS`],
    ['Coinbase maturity', `${formatNumber(config.maturity_confirmations)} blocks`],
    ['Automatic payouts', config.auto_payouts ? 'Enabled' : 'Disabled'],
  ]
  const list = document.getElementById('pool-config-list')
  clear(list)
  for (const [label, value] of configRows) {
    const row = el('div', 'row')
    row.append(el('dt', null, label), el('dd', null, value))
    list.append(row)
  }

  setText('overview-cta-endpoint', endpointText(config))
  renderTables(data)
  markUpdated('overview-updated')
  setState(stateBox, 'ok', 'Live data loaded', 'Every value above came from the pool API in this request.')
}

async function load() {
  try {
    const data = await apiGet('/pool/status')
    lastSuccess = data
    if (firstLoad) setState(stateBox, 'loading', 'Loading pool data', 'Reading the live API…')
    firstLoad = false
    render(data)
  } catch (error) {
    setDot('hero-dot', error.status === 0 ? 'error' : 'offline')
    setText(
      'hero-status-text',
      'The pool API is unavailable. No live values are being displayed.',
    )
    setText('hero-endpoint', 'Unavailable')
    if (lastSuccess) {
      setState(
        stateBox,
        'offline',
        'Refresh failed',
        `${error.message} Showing the last successful snapshot, which may be stale.`,
      )
      setText('overview-updated', 'Last refresh failed')
    } else {
      setState(
        stateBox,
        'error',
        'Pool API unavailable',
        `${error.message} Start the backend and reload this page.`,
      )
      for (const id of [
        'stat-miners', 'stat-active', 'stat-accepted', 'stat-blocks', 'stat-hashrate',
        'stat-reward', 'stat-fee', 'stat-height', 'stat-round',
      ]) setText(id, '—')
      setService('api', 'error', 'Unavailable')
      setService('node', 'unknown', 'Unknown')
      setService('stratum', 'unknown', 'Unknown')
      setService('db', 'unknown', 'Unknown')
      renderTables({})
    }
  }
}

load()
startPolling(load, 15000)
