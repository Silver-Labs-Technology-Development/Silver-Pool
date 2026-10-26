import {
  apiGet,
  formatNumber,
  formatTime,
  initLayout,
  markUpdated,
  setState,
  setText,
} from './site.js'

initLayout()

const stateBox = document.getElementById('status-state')
const banner = document.getElementById('readiness-banner')
const refresh = document.getElementById('status-refresh')

function setCheck(id, value, detail) {
  setText(`check-${id}`, value)
  if (detail !== undefined) setText(`check-${id}-detail`, detail)
}

function duration(seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value < 0) return '—'
  if (value < 60) return `${Math.floor(value)}s`
  if (value < 3600) return `${Math.floor(value / 60)}m ${Math.floor(value % 60)}s`
  return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`
}

function templateAge(timestamp) {
  if (!timestamp) return 'No template'
  const age = Math.max(0, Date.now() / 1000 - Number(timestamp))
  return `${duration(age)} ago`
}

function showError(id, message) {
  const container = document.getElementById(id)
  if (!container) return
  setState(container, 'error', 'Error reported by the pool API', message)
}

function clearError(id) {
  const container = document.getElementById(id)
  if (container) {
    while (container.firstChild) container.removeChild(container.firstChild)
  }
}

function render(data) {
  const checks = data.checks || {}
  const db = checks.database || {}
  const nodeChecks = checks.node || {}
  const stratumChecks = checks.stratum || {}
  const node = data.node || {}
  const stratum = data.stratum || {}
  const ready = Boolean(data.ready)

  setCheck('api', 'Online', `Version ${data.version || '—'}`)
  setCheck('db', db.healthy ? 'Healthy' : 'Degraded', db.error || 'SQLite WAL + migrations')
  setCheck(
    'node',
    node.connected ? (node.synced ? 'Synced' : 'Connected') : 'Offline',
    node.connected
      ? `Height ${formatNumber(node.blocks)} / ${formatNumber(node.headers)}`
      : nodeChecks.error || 'RPC unavailable',
  )
  setCheck(
    'stratum',
    stratum.listening ? 'Listening' : 'Stopped',
    stratum.current_job_id ? `Job ${stratum.current_job_id}` : 'No current job',
  )

  if (ready) {
    setState(
      banner,
      'ok',
      'Pool is ready',
      'Database, BTCS node, Stratum listener and block-template job all passed readiness checks. This means the pool can accept miners; it does not mean payouts are enabled.',
    )
  } else {
    setState(
      banner,
      'offline',
      'Pool is not ready',
      'At least one readiness check failed. Miners may be disconnected or receive no usable work until the failed component recovers. No values below are inferred.',
    )
  }

  setText('node-chain', (node.chain || data.checks?.node?.chain || '—').toUpperCase?.() || '—')
  setText('node-connected', node.connected ? 'Yes' : 'No')
  setText(
    'node-blocks',
    node.connected ? `${formatNumber(node.blocks)} / ${formatNumber(node.headers)}` : '—',
  )
  setText(
    'node-progress',
    node.connected ? `${(Number(node.verification_progress || 0) * 100).toFixed(3)}%` : '—',
  )
  setText('node-ibd', node.connected ? (node.initial_block_download ? 'Yes' : 'No') : '—')
  setText('node-connections', node.connected ? formatNumber(node.connections) : '—')
  setText(
    'node-difficulty',
    node.connected && node.difficulty !== null && node.difficulty !== undefined
      ? String(node.difficulty)
      : '—',
  )
  setText('node-mempool', node.connected ? `${formatNumber(node.mempool_transactions)} transactions` : '—')
  setText('node-checked', node.checked_at ? formatTime(node.checked_at) : '—')
  if (node.error) showError('node-error', node.error)
  else clearError('node-error')

  setText('stratum-listening', stratum.listening ? 'Yes' : 'No')
  setText('stratum-clients', formatNumber(stratum.clients))
  setText('stratum-authorized', formatNumber(stratum.authorized_clients))
  setText('stratum-job', stratum.current_job_id || 'None')
  setText('stratum-height', stratum.current_height ? formatNumber(stratum.current_height) : '—')
  setText('stratum-round', stratum.current_round_id || '—')
  setText('stratum-template', templateAge(stratum.last_template_at))
  setText('stratum-uptime', duration(stratum.uptime_seconds))
  if (stratum.last_template_error || stratumChecks.last_template_error) {
    showError(
      'stratum-error',
      stratum.last_template_error || stratumChecks.last_template_error,
    )
  } else {
    clearError('stratum-error')
  }

  markUpdated('status-updated')
  const warnings = Array.isArray(node.warnings) ? node.warnings.filter(Boolean) : []
  if (!ready && !warnings.length) {
    setState(
      stateBox,
      'offline',
      'Readiness incomplete',
      `Database: ${db.healthy ? 'healthy' : 'unavailable'} · Node: ${
        node.connected ? (node.synced ? 'synced' : 'not synced') : 'offline'
      } · Stratum: ${stratum.listening ? 'listening' : 'stopped'} · Fresh template: ${
        stratumChecks.template_fresh ? 'yes' : 'no'
      }.`,
    )
  } else if (warnings.length) {
    setState(stateBox, 'offline', 'Node warnings', warnings.join(' '))
  } else {
    setState(
      stateBox,
      'ok',
      'Status loaded from the live API',
      'This page reports the checks returned by /api/status in this request.',
    )
  }
}

function renderFailure(error) {
  setCheck('api', 'Offline', error.status ? `HTTP ${error.status}` : 'No response')
  for (const id of ['db', 'node', 'stratum']) setCheck(id, 'Unknown', 'API unavailable')
  setState(
    stateBox,
    'error',
    'Status unavailable',
    `${error.message} The website cannot verify the pool, so it is not reporting a healthy state.`,
  )
  setState(
    banner,
    'error',
    'Status unavailable',
    `${error.message} The website cannot verify the pool, so it is not reporting a healthy state.`,
  )
  const nodeContainer = document.getElementById('node-error')
  const stratumContainer = document.getElementById('stratum-error')
  if (nodeContainer) {
    setState(nodeContainer, 'error', 'No node data', 'The API status request failed.')
  }
  if (stratumContainer) {
    setState(stratumContainer, 'error', 'No Stratum data', 'The API status request failed.')
  }
  setText('status-updated', 'Last refresh failed')
}

async function load() {
  try {
    const data = await apiGet('/status')
    render(data)
  } catch (error) {
    renderFailure(error)
  }
}

refresh.addEventListener('click', load)
load()
setInterval(load, 15000)
