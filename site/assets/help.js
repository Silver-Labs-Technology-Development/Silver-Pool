import {
  apiGet,
  formatNumber,
  initCopyButtons,
  initLayout,
  setState,
  setText,
} from './site.js'

initLayout()

const stateBox = document.getElementById('help-state')

function render(data) {
  const config = data.config || {}
  const stratum = config.stratum || {}
  const node = data.node || {}
  const live = data.stratum || {}
  const readyForMiners =
    node.connected && node.synced && live.listening && Boolean(live.current_job_id)
  const endpoint = stratum.endpoint
  const ipv6Host = typeof stratum.host === 'string' && stratum.host.includes(':')
  const ncHost = ipv6Host ? `-6 ${stratum.host}` : stratum.host

  setText('help-endpoint', endpoint || 'Not configured')
  setText(
    'help-endpoint-note',
    endpoint
      ? stratum.password_required
        ? 'A pool password is required for authorization.'
        : 'Any non-empty password is accepted; use “x” for compatibility.'
      : 'The operator must set BTCS_PUBLIC_STRATUM_HOST before a public endpoint is advertised.',
  )
  setText('help-ready', readyForMiners ? 'Ready for miners' : 'Not ready')
  setText(
    'help-ready-note',
    readyForMiners
      ? `Stratum is listening with job ${live.current_job_id}. Payouts remain disabled.`
      : 'At least one of node sync, Stratum listener or current job is missing.',
  )
  setText('help-network', node.connected ? (node.chain || config.network || '—').toUpperCase?.() : 'Node offline')
  setText(
    'help-node-note',
    node.connected
      ? `Height ${formatNumber(node.blocks)} of ${formatNumber(node.headers)} · ${
          node.initial_block_download ? 'initial block download' : 'verification complete'
        }`
      : node.error || 'The BTCS node RPC is unavailable.',
  )
  setText(
    'help-command',
    endpoint
      ? `nc -vz ${ncHost} ${stratum.port}\n# or\ntelnet ${stratum.host} ${stratum.port}`
      : 'The pool has not configured a public Stratum endpoint.\nDo not substitute a hostname from an old guide.',
  )
  initCopyButtons()

  if (endpoint && readyForMiners) {
    setState(
      stateBox,
      'ok',
      'Live state loaded',
      `The pool is advertising ${endpoint} and currently has a usable job. Use the exact endpoint and username format from the connection guide.`,
    )
  } else if (endpoint) {
    setState(
      stateBox,
      'offline',
      'Endpoint configured, pool not fully ready',
      'The endpoint is advertised, but a readiness component is missing. Check Service Status before assuming the miner is at fault.',
    )
  } else {
    setState(
      stateBox,
      'offline',
      'No public endpoint configured',
      'Mining cannot be configured from this site until the operator supplies a reachable public Stratum host and port.',
    )
  }
}

async function load() {
  setState(stateBox, 'loading', 'Loading live diagnostics', 'Reading the pool API configuration and readiness state…')
  try {
    const data = await apiGet('/pool/status')
    render(data)
  } catch (error) {
    setText('help-endpoint', 'Unavailable')
    setText('help-endpoint-note', 'The public configuration could not be loaded.')
    setText('help-ready', 'Unknown')
    setText('help-ready-note', 'The status API did not respond.')
    setText('help-network', 'Unknown')
    setText('help-node-note', 'No node data was returned.')
    setText(
      'help-command',
      'The pool API is unavailable, so no connection command can be generated.',
    )
    setState(
      stateBox,
      'error',
      'Live diagnostics unavailable',
      `${error.message} This page is showing no endpoint or readiness claim.`,
    )
  }
}

load()
setInterval(load, 30000)
