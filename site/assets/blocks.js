import {
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
} from './site.js'

initLayout()

const stateBox = document.getElementById('blocks-state')
const body = document.getElementById('blocks-body')
const filter = document.getElementById('block-status')

function render(blocks, status) {
  clear(body)
  if (!blocks.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', status === 'all' ? 'No blocks have been found by this pool yet.' : `No ${status} blocks are recorded.`)
    td.colSpan = 7
    tr.append(td)
    body.append(tr)
    return
  }
  for (const block of blocks) {
    const tr = el('tr')
    tr.append(el('td', 'mono', block.height))
    const hash = el('td', 'hash mono', block.hash)
    hash.title = block.hash
    tr.append(hash)
    const miner = el('td')
    if (block.miner) {
      const link = el('a', null, block.miner)
      link.href = `../miner/?miner=${encodeURIComponent(block.miner)}`
      miner.append(link)
    } else {
      miner.textContent = '—'
    }
    tr.append(miner)
    tr.append(el('td', 'mono', block.net_reward_btcs ? `${block.net_reward_btcs} BTCS` : formatBtcS(block.net_reward_satoshi)))
    const statusCell = el('td')
    statusCell.append(statusBadge(block.status))
    tr.append(statusCell)
    tr.append(el('td', 'mono', formatNumber(block.confirmations)))
    tr.append(el('td', null, formatTime(block.found_at)))
    body.append(tr)
  }
}

async function load() {
  const status = filter.value
  setState(stateBox, 'loading', 'Loading blocks', 'Reading the persistent block history…')
  try {
    const data = await apiGet(`/pool/blocks?limit=100&status=${encodeURIComponent(status)}`)
    render(data.blocks || [], status)
    setText('blocks-count', `${formatNumber(data.count)} block${data.count === 1 ? '' : 's'} shown`)
    setState(stateBox, 'ok', 'Block history loaded', 'Confirmation counts come from the BTCS node height recorded by the pool.')
  } catch (error) {
    clear(body)
    const tr = el('tr')
    const td = el('td', 'table-empty', 'Block data is unavailable.')
    td.colSpan = 7
    tr.append(td)
    body.append(tr)
    setText('blocks-count', 'API unavailable')
    setState(stateBox, 'error', 'Block data unavailable', `${error.message} No block records are being invented.`)
  }
}

filter.addEventListener('change', load)
document.getElementById('blocks-refresh').addEventListener('click', load)
load()
setInterval(load, 30000)
