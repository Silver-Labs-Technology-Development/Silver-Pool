import {
  apiGet,
  clear,
  el,
  formatHashrate,
  formatNumber,
  formatTime,
  initLayout,
  markUpdated,
  setState,
  setText,
} from './site.js'

initLayout()

const canvas = document.getElementById('hashrate-chart')
const empty = document.getElementById('chart-empty')
const stateBox = document.getElementById('stats-state')
const chartState = document.getElementById('chart-state')
const historyBody = document.getElementById('history-body')
let range = '24h'
let history = []
let series = []
let lastStats = null

function addStats(stats) {
  setText('stat-accepted', formatNumber(stats.accepted_shares))
  setText('stat-rejected', `${formatNumber(stats.rejected_shares)} rejected`)
  setText('stat-difficulty', formatNumber(stats.total_difficulty || 0, 2))
  const hashrate = formatHashrate(stats.estimated_hashrate_24h)
  setText('stat-hashrate', `${hashrate.value} ${hashrate.unit}`)
  setText('stat-miners', formatNumber(stats.total_miners))
  setText('stat-active', `${formatNumber(stats.active_miners_24h)} active in 24h`)
}

function renderHistory() {
  clear(historyBody)
  const rows = history.slice(-24).reverse()
  if (!rows.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', 'No history buckets were returned.')
    td.colSpan = 4
    tr.append(td)
    historyBody.append(tr)
    return
  }
  for (const point of rows) {
    const tr = el('tr')
    tr.append(el('td', null, formatTime(point.timestamp)))
    tr.append(el('td', 'mono', formatNumber(point.shares)))
    tr.append(el('td', 'mono', formatNumber(point.difficulty, 4)))
    const hr = formatHashrate(point.hashrate)
    tr.append(el('td', 'mono', `${hr.value} ${hr.unit}`))
    historyBody.append(tr)
  }
}

function drawChart() {
  if (!canvas) return
  const parent = canvas.parentElement
  const width = Math.max(320, parent.clientWidth - 32)
  const height = canvas.clientHeight || 300
  const dpr = window.devicePixelRatio || 1
  canvas.width = Math.floor(width * dpr)
  canvas.height = Math.floor(height * dpr)
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)

  const values = series.map((point) => Number(point.hashrate) || 0)
  const maxValue = Math.max(...values, 1)
  const hasData = values.some((value) => value > 0)
  empty.hidden = hasData
  empty.textContent = hasData
    ? ''
    : 'No accepted shares in this window. Hashrate is not estimated without share data.'

  const pad = { left: 66, right: 14, top: 18, bottom: 30 }
  const plotWidth = width - pad.left - pad.right
  const plotHeight = height - pad.top - pad.bottom
  ctx.strokeStyle = '#dfe3e7'
  ctx.lineWidth = 1
  ctx.fillStyle = '#66707a'
  ctx.font = '11px Inter, system-ui, sans-serif'

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotHeight / 4) * i
    ctx.beginPath()
    ctx.moveTo(pad.left, y)
    ctx.lineTo(width - pad.right, y)
    ctx.stroke()
    const value = maxValue * (1 - i / 4)
    const label = formatHashrate(value)
    ctx.fillText(`${label.value} ${label.unit}`, 4, y + 4)
  }

  if (series.length) {
    const xAt = (index) => {
      if (series.length === 1) return pad.left + plotWidth / 2
      return pad.left + (plotWidth * index) / (series.length - 1)
    }
    const yAt = (value) => pad.top + plotHeight - (value / maxValue) * plotHeight

    const gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom)
    gradient.addColorStop(0, 'rgba(26, 111, 186, 0.24)')
    gradient.addColorStop(1, 'rgba(26, 111, 186, 0.01)')
    ctx.beginPath()
    series.forEach((point, index) => {
      const x = xAt(index)
      const y = yAt(Number(point.hashrate) || 0)
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    if (series.length > 1) {
      ctx.lineTo(xAt(series.length - 1), height - pad.bottom)
      ctx.lineTo(xAt(0), height - pad.bottom)
      ctx.closePath()
      ctx.fillStyle = gradient
      ctx.fill()
    }

    ctx.beginPath()
    series.forEach((point, index) => {
      const x = xAt(index)
      const y = yAt(Number(point.hashrate) || 0)
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.strokeStyle = '#1a6fba'
    ctx.lineWidth = 2
    ctx.stroke()

    if (series.length === 1) {
      ctx.beginPath()
      ctx.arc(xAt(0), yAt(Number(series[0].hashrate) || 0), 3, 0, Math.PI * 2)
      ctx.fillStyle = '#1a6fba'
      ctx.fill()
    }

    const labelIndexes = series.length > 2 ? [0, Math.floor((series.length - 1) / 2), series.length - 1] : [0, series.length - 1]
    for (const index of new Set(labelIndexes)) {
      const point = series[index]
      if (!point) continue
      const label = new Date(Number(point.timestamp) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      const x = xAt(index)
      ctx.fillStyle = '#66707a'
      const widthLabel = ctx.measureText(label).width
      const left = Math.min(Math.max(pad.left, x - widthLabel / 2), width - pad.right - widthLabel)
      ctx.fillText(label, left, height - 8)
    }
  }
}

async function loadChart() {
  try {
    const data = await apiGet(`/pool/history/hashrate?range=${encodeURIComponent(range)}`)
    history = data.history || []
    series = history
    setText('chart-window', `Window: ${data.range || range}`)
    setText('chart-bucket', `Bucket: ${formatNumber(data.bucket_seconds)}s`)
    setText('stats-updated', `Updated ${new Date().toLocaleTimeString()}`)
    renderHistory()
    drawChart()
    const nonEmpty = history.filter((point) => Number(point.shares) > 0).length
    if (nonEmpty === 0) {
      setState(chartState, 'empty', 'No share history yet', `No accepted shares were recorded in the ${range} window.`)
    } else {
      setState(chartState, 'ok', 'Hashrate history loaded', `${formatNumber(nonEmpty)} buckets contain accepted shares in the selected window.`)
    }
  } catch (error) {
    history = []
    series = []
    renderHistory()
    drawChart()
    setState(chartState, 'error', 'Hashrate history unavailable', error.message)
  }
}

async function loadStats() {
  try {
    const data = await apiGet('/pool/statistics')
    lastStats = data
    addStats(data.totals || {})
    setState(stateBox, 'ok', 'Live totals loaded', 'Totals came from the pool database in this request.')
    markUpdated('stats-updated')
  } catch (error) {
    setState(stateBox, 'error', 'Pool statistics unavailable', `${error.message} No values are being guessed.`)
    for (const id of ['stat-accepted', 'stat-difficulty', 'stat-hashrate', 'stat-miners']) setText(id, '—')
  }
}

async function load() {
  await Promise.all([loadStats(), loadChart()])
}

document.querySelectorAll('[data-range]').forEach((button) => {
  button.addEventListener('click', async () => {
    range = button.dataset.range
    document.querySelectorAll('[data-range]').forEach((item) => item.classList.toggle('is-active', item === button))
    await loadChart()
  })
})

if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(() => drawChart()).observe(canvas.parentElement)
}
window.addEventListener('resize', drawChart)
load()
setInterval(load, 30000)
