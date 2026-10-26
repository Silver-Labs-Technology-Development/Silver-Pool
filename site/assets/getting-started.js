import {
  apiGet,
  initCopyButtons,
  initLayout,
  setState,
  setText,
} from './site.js'

initLayout()

const stateBox = document.getElementById('connect-state')
const content = document.getElementById('connect-content')

function showUnavailable(message) {
  content.hidden = true
  setState(stateBox, 'offline', 'No public Stratum endpoint is configured', message)
}

function render(config) {
  const stratum = config.stratum || {}
  if (!stratum.configured || !stratum.endpoint) {
    showUnavailable(
      'The pool operator has not set BTCS_PUBLIC_STRATUM_HOST, so Silver Pool is not advertising a hostname or port. A valid endpoint must be configured and externally reachable before it is shown here.',
    )
    return
  }
  content.hidden = false
  const endpoint = stratum.endpoint
  const password = stratum.password_required ? 'YOUR_POOL_PASSWORD' : 'x'
  const user = 'YOUR_BTCS_ACCOUNT.WORKER'
  const url = `stratum+tcp://${endpoint}`
  setText('stratum-endpoint', endpoint)
  setText('connect-algorithm', config.algorithm || 'SHA256d')
  setText('connect-difficulty', String(stratum.difficulty ?? '—'))
  setText('connect-extranonce', `${stratum.extranonce2_size ?? '—'} bytes`)
  setText('connect-fee', `${config.fee_percent}%`)
  setText('connect-reward', config.reward_method || 'PPLNS')
  setText(
    'password-guidance',
    stratum.password_required
      ? 'the operator has configured a pool password. Use the password you were given; authorization fails without it.'
      : 'no pool password is configured. Any non-empty password is accepted; use “x” for compatibility.',
  )
  setText(
    'account-guidance',
    'Use a stable account label that you control. A BTCS address can be used as the account label, but the current release does not use it for automatic payouts. The worker suffix identifies the device.',
  )
  setText(
    'example-cpuminer',
    `cpuminer --algo=sha256d --url=${url} --user=${user} --pass=${password}`,
  )
  setText(
    'example-cgminer',
    `cgminer -o ${url} -u ${user} -p ${password}`,
  )
  setText(
    'example-bfgminer',
    `bfgminer -o ${url} -u ${user} -p ${password}`,
  )
  setState(
    stateBox,
    'ok',
    'Endpoint loaded from the pool API',
    `This connection page is showing ${endpoint}. Do not use a hostname copied from documentation if it differs from this value.`,
  )
  initCopyButtons()
}

async function load() {
  setState(stateBox, 'loading', 'Loading pool configuration', 'Reading the public configuration from the live API…')
  try {
    const config = await apiGet('/pool/config')
    render(config)
  } catch (error) {
    content.hidden = true
    setState(stateBox, 'error', 'Configuration unavailable', `${error.message} No endpoint is being guessed.`)
  }
}

load()
