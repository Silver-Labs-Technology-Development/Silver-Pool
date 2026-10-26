import {
  ApiError,
  apiGet,
  clear,
  el,
  formatBtcS,
  formatNumber,
  formatTime,
  initLayout,
  setState,
  setText,
  statusBadge,
  timeAgo,
} from './site.js'

initLayout()

const stateBox = document.getElementById('miner-state')
const content = document.getElementById('miner-content')
const input = document.getElementById('miner-search')
const form = document.getElementById('miner-search-form')
const params = new URLSearchParams(window.location.search)
let current = params.get('miner') || ''

function workerRow(worker) {
  const tr = el('tr')
  tr.append(el('td', null, worker.name || '—'))
  tr.append(el('td', 'mono', formatNumber(worker.accepted_shares)))
  tr.append(el('td', null, formatTime(worker.created_at)))
  tr.append(el('td', null, worker.last_seen_at ? timeAgo(worker.last_seen_at) : '—'))
  return tr
}

function shareRow(share) {
  const tr = el('tr')
  tr.append(el('td', 'mono', share.job_id || '—'))
  tr.append(el('td', 'mono', share.round_height ?? '—'))
  tr.append(el('td', 'mono', formatNumber(share.difficulty, 4)))
  const result = el('td')
  result.append(statusBadge(share.accepted ? 'accepted' : share.stale ? 'stale' : 'rejected'))
  tr.append(result)
  tr.append(el('td', null, share.reject_reason || (share.stale ? 'stale' : '—')))
  tr.append(el('td', null, formatTime(share.created_at)))
  return tr
}

function blockRow(block) {
  const tr = el('tr')
  tr.append(el('td', 'mono', block.height))
  const hash = el('td', 'hash mono', block.hash)
  hash.title = block.hash
  tr.append(hash)
  tr.append(el('td', 'mono', block.net_reward_btcs ? `${block.net_reward_btcs} BTCS` : formatBtcS(block.net_reward_satoshi)))
  const status = el('td')
  status.append(statusBadge(block.status))
  tr.append(status)
  tr.append(el('td', 'mono', formatNumber(block.confirmations)))
  tr.append(el('td', null, formatTime(block.found_at)))
  return tr
}

function tableRows(body, rows, renderRow, emptyMessage, columns) {
  clear(body)
  if (!rows?.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', emptyMessage)
    td.colSpan = columns
    tr.append(td)
    body.append(tr)
    return
  }
  rows.forEach((row) => body.append(renderRow(row)))
}

function render(miner, shares) {
  content.hidden = false
  setText('miner-name', miner.username)
  setText(
    'miner-meta',
    `Created ${formatTime(miner.created_at)} · Last seen ${miner.last_seen_at ? formatTime(miner.last_seen_at) : 'never'}`,
  )
  const active = miner.last_seen_at && Date.now() / 1000 - miner.last_seen_at < 600
  const dot = document.getElementById('miner-dot')
  dot.className = `dot dot-${active ? 'online' : 'unknown'}`
  setText('miner-status', active ? 'Active in the last 10 minutes' : 'No recent activity')
  setText('miner-available', formatBtcS(miner.available_satoshi))
  setText('miner-immature', formatBtcS(miner.immature_satoshi))
  setText('miner-accepted', formatNumber(miner.accepted_shares))
  setText('miner-rejected', `${formatNumber(miner.rejected_shares)} rejected`)
  setText('miner-workers', formatNumber(miner.workers))
  tableRows(
    document.getElementById('miner-workers-body'),
    miner.worker_rows,
    workerRow,
    'No workers are registered for this miner.',
    4,
  )
  tableRows(
    document.getElementById('miner-shares-body'),
    shares,
    shareRow,
    'No shares have been recorded for this miner.',
    6,
  )
  tableRows(
    document.getElementById('miner-blocks-body'),
    miner.recent_blocks,
    blockRow,
    'This miner has not found a block recorded by the pool.',
    6,
  )
  setState(stateBox, 'ok', 'Miner record loaded', 'All values are from the persistent pool database.')
  document.title = `${miner.username} — Silver Pool`
}

async function load() {
  if (!current) {
    content.hidden = true
    setState(stateBox, 'empty', 'Search for a miner', 'Enter an account name above to view its workers, shares and found blocks.')
    return
  }
  input.value = current
  setState(stateBox, 'loading', 'Loading miner', `Reading records for ${current}…`)
  try {
    const [miner, sharesData] = await Promise.all([
      apiGet(`/pool/miner/${encodeURIComponent(current)}`),
      apiGet(`/pool/miner/${encodeURIComponent(current)}/shares?limit=50`),
    ])
    render(miner, sharesData.shares || [])
  } catch (error) {
    content.hidden = true
    if (error instanceof ApiError && error.status === 404) {
      setState(stateBox, 'offline', 'Miner not found', `No miner named “${current}” exists in this pool database.`)
      document.title = 'Miner not found — Silver Pool'
    } else {
      setState(stateBox, 'error', 'Miner data unavailable', `${error.message} No records are being displayed.`)
    }
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault()
  const value = input.value.trim()
  if (!value) return
  current = value
  const url = new URL(window.location.href)
  url.searchParams.set('miner', value)
  history.pushState({ miner: value }, '', url)
  load()
})

window.addEventListener('popstate', () => {
  const next = new URLSearchParams(window.location.search).get('miner') || ''
  current = next
  load()
})

load()
