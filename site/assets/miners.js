import {
  apiGet,
  clear,
  el,
  formatBtcS,
  formatNumber,
  initLayout,
  setState,
  setText,
  timeAgo,
} from './site.js'

initLayout()

const stateBox = document.getElementById('miners-state')
const body = document.getElementById('miners-body')
const input = document.getElementById('miner-search')
const form = document.getElementById('miner-search-form')
let debounce = null

function render(miners, search) {
  clear(body)
  if (!miners.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', search ? `No miners matched “${search}”.` : 'No miners have authorized with this pool yet.')
    td.colSpan = 7
    tr.append(td)
    body.append(tr)
    return
  }
  for (const miner of miners) {
    const tr = el('tr')
    const nameCell = el('td')
    const link = el('a', null, miner.username)
    link.href = `../miner/?miner=${encodeURIComponent(miner.username)}`
    nameCell.append(link)
    tr.append(nameCell)
    tr.append(el('td', 'mono', formatNumber(miner.workers)))
    tr.append(el('td', 'mono', formatNumber(miner.accepted_shares)))
    tr.append(el('td', 'mono', formatNumber(miner.rejected_shares)))
    tr.append(el('td', 'mono', formatBtcS(miner.immature_satoshi)))
    tr.append(el('td', 'mono', formatBtcS(miner.available_satoshi)))
    const seen = el('td', null, miner.last_seen_at ? timeAgo(miner.last_seen_at) : '—')
    if (miner.last_seen_at) seen.title = new Date(miner.last_seen_at * 1000).toLocaleString()
    tr.append(seen)
    body.append(tr)
  }
}

async function load() {
  const search = input.value.trim()
  setState(stateBox, 'loading', 'Loading miners', 'Reading the live pool API…')
  try {
    const data = await apiGet(`/pool/miners?limit=50&search=${encodeURIComponent(search)}`)
    const miners = data.miners || []
    render(miners, search)
    setText('miners-count', `${formatNumber(miners.length)} miner${miners.length === 1 ? '' : 's'} shown${search ? ` for “${search}”` : ''}.`)
    setState(stateBox, 'ok', 'Miner list loaded', 'Balances and share counts are from the persistent pool database.')
  } catch (error) {
    clear(body)
    const tr = el('tr')
    const td = el('td', 'table-empty', 'Miner data is unavailable.')
    td.colSpan = 7
    tr.append(td)
    body.append(tr)
    setText('miners-count', 'API unavailable')
    setState(stateBox, 'error', 'Miner data unavailable', `${error.message} No miner records are being invented.`)
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault()
  load()
})
input.addEventListener('input', () => {
  clearTimeout(debounce)
  debounce = setTimeout(load, 300)
})
document.getElementById('miner-clear').addEventListener('click', () => {
  input.value = ''
  load()
})
load()
