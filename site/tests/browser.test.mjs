import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, before, describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

const siteRoot = fileURLToPath(new URL('..', import.meta.url))
const chromeBin =
  process.env.CHROME_BIN ||
  ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'].find(
    (candidate) => existsSync(candidate),
  )

const NOW = Math.floor(Date.now() / 1000)
const CONFIG = {
  network: 'regtest',
  algorithm: 'SHA256d',
  reward_method: 'PPLNS',
  fee_percent: 2,
  min_payout_btcs: 0.01,
  payout_interval_seconds: 300,
  auto_payouts: false,
  payouts_enabled: false,
  maturity_confirmations: 200,
  stratum: {
    configured: true,
    host: 'pool.example',
    port: 3333,
    endpoint: 'pool.example:3333',
    password_required: false,
    difficulty: 1,
    extranonce2_size: 4,
  },
  api: { version: '0.2.0', rate_limit_per_minute: 240 },
}

const NODE = {
  connected: true,
  network: 'regtest',
  chain: 'regtest',
  blocks: 123,
  headers: 123,
  verification_progress: 1,
  initial_block_download: false,
  synced: true,
  connections: 2,
  difficulty: 4.65e-10,
  mempool_transactions: 0,
  warnings: [],
  error: null,
  checked_at: NOW,
}

const STRATUM = {
  listening: true,
  clients: 1,
  authorized_clients: 1,
  current_job_id: '42',
  current_height: 124,
  current_round_id: '124-aaaa',
  current_difficulty: 1,
  last_template_at: NOW,
  last_template_error: null,
  uptime_seconds: 125,
}

const POOL = {
  total_miners: 3,
  total_workers: 4,
  total_shares: 15,
  accepted_shares: 12,
  rejected_shares: 3,
  total_blocks: 1,
  mature_blocks: 0,
  immature_blocks: 1,
  orphaned_blocks: 0,
  active_miners_24h: 2,
  estimated_hashrate_24h: 1234567,
  total_difficulty: 18.5,
}

const BLOCKS = [
  {
    height: 123,
    hash: 'ab'.repeat(32),
    coinbase_value_satoshi: 500000000,
    fee_satoshi: 10000000,
    net_reward_satoshi: 490000000,
    coinbase_value_btcs: '5.00000000',
    net_reward_btcs: '4.90000000',
    status: 'immature',
    miner: 'alice',
    round_id: '123-bbbb',
    found_at: NOW - 90,
    matured_at: null,
    confirmations: 1,
  },
]

const MINERS = [
  {
    username: 'alice',
    created_at: NOW - 86400,
    last_seen_at: NOW - 60,
    available_satoshi: 0,
    immature_satoshi: 490000000,
    total_satoshi: 490000000,
    available_btcs: '0.00000000',
    immature_btcs: '4.90000000',
    total_btcs: '4.90000000',
    workers: 2,
    accepted_shares: 8,
    rejected_shares: 1,
  },
  {
    username: 'bob',
    created_at: NOW - 43200,
    last_seen_at: NOW - 300,
    available_satoshi: 0,
    immature_satoshi: 0,
    total_satoshi: 0,
    available_btcs: '0.00000000',
    immature_btcs: '0.00000000',
    total_btcs: '0.00000000',
    workers: 1,
    accepted_shares: 4,
    rejected_shares: 2,
  },
]

const SHARES = {
  alice: [
    {
      job_id: '42',
      extranonce2: '00000000',
      ntime: '01020304',
      nonce: '00000001',
      difficulty: 2,
      accepted: true,
      stale: false,
      reject_reason: null,
      created_at: NOW - 30,
      worker: 'rig1',
      round_height: 124,
    },
  ],
  bob: [
    {
      job_id: '42',
      extranonce2: '00000000',
      ntime: '01020304',
      nonce: '00000002',
      difficulty: 1,
      accepted: false,
      stale: true,
      reject_reason: 'stale-job',
      created_at: NOW - 40,
      worker: 'rig9',
      round_height: 124,
    },
  ],
}

const MINER_DETAILS = Object.fromEntries(
  MINERS.map((miner) => [
    miner.username,
    {
      ...miner,
      worker_rows: [
        {
          name: 'rig1',
          created_at: NOW - 86400,
          last_seen_at: NOW - 60,
          accepted_shares: miner.username === 'alice' ? 8 : 4,
        },
      ],
      recent_blocks: miner.username === 'alice' ? BLOCKS : [],
    },
  ]),
)

const SHARE_ROWS = [
  {
    miner: 'alice',
    worker: 'rig1',
    job_id: '42',
    difficulty: 2,
    accepted: true,
    stale: false,
    reject_reason: null,
    created_at: NOW - 30,
    round_height: 124,
  },
  {
    miner: 'bob',
    worker: 'rig9',
    job_id: '42',
    difficulty: 1,
    accepted: false,
    stale: true,
    reject_reason: 'stale-job',
    created_at: NOW - 40,
    round_height: 124,
  },
]

const ROUND = {
  round_id: '124-aaaa',
  height: 124,
  status: 'active',
  total_shares: 2,
  total_difficulty: 3,
  pool_fee_satoshi: 0,
  started_at: NOW - 3600,
  ended_at: null,
}

const RATE_LIMIT = 240
const DOCS = {
  openapi: '/api/openapi.json',
  version: '0.2.0',
  authentication: 'none',
  rate_limit_per_minute: RATE_LIMIT,
  envelope: {
    success: { ok: true, data: {}, meta: {} },
    error: { ok: false, error: {}, meta: {} },
  },
  endpoints: [
    ['GET', '/api/health', 'Liveness'],
    ['GET', '/api/ready', 'Readiness'],
    ['GET', '/api/status', 'Overall status'],
    ['GET', '/api/pool/status', 'Overview'],
    ['GET', '/api/pool/statistics', 'Totals'],
    ['GET', '/api/pool/history/hashrate?range=24h', 'Hashrate history'],
    ['GET', '/api/pool/miners?limit=50&search=', 'Miner list'],
    ['GET', '/api/pool/miner/{username}', 'Miner detail'],
    ['GET', '/api/pool/miner/{username}/shares?limit=50', 'Miner shares'],
    ['GET', '/api/pool/shares/recent?limit=20', 'Recent shares'],
    ['GET', '/api/pool/blocks?limit=50&status=all', 'Blocks'],
    ['GET', '/api/pool/blocks/recent?limit=20', 'Recent blocks'],
    ['GET', '/api/pool/fee-ledger?limit=50', 'Pool fee ledger'],
    ['GET', '/api/pool/rounds/current', 'Current round'],
    ['GET', '/api/pool/config', 'Public configuration'],
  ].map(([method, path, description]) => ({ method, path, description })),
}

function envelope(data) {
  return { ok: true, data, meta: { timestamp: Date.now() / 1000, request_id: 'browser-test' } }
}

function errorEnvelope() {
  return {
    ok: false,
    error: { code: 'temporarily_unavailable', message: 'Test API is unavailable' },
    meta: { timestamp: Date.now() / 1000, request_id: 'browser-test' },
  }
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload)
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body),
  })
  response.end(body)
}

function history(range) {
  const buckets = { '1h': 60, '6h': 300, '24h': 900, '7d': 3600 }
  const seconds = buckets[range] || 900
  return {
    range: range || '24h',
    bucket_seconds: seconds,
    history: Array.from({ length: 6 }, (_, index) => ({
      timestamp: NOW - (5 - index) * seconds,
      difficulty: index === 5 ? 4 : 0,
      shares: index === 5 ? 2 : 0,
      hashrate: index === 5 ? (4 * 2 ** 32) / seconds : 0,
    })),
  }
}

function createMockApi() {
  let mode = 'ok'
  const server = createServer((request, response) => {
    const url = new URL(request.url || '/', 'http://127.0.0.1')
    if (url.pathname === '/__control') {
      mode = url.searchParams.get('mode') === 'error' ? 'error' : 'ok'
      sendJson(response, 200, { mode })
      return
    }
    if (!url.pathname.startsWith('/api')) {
      sendJson(response, 404, { ok: false, error: { code: 'not_found', message: 'not found' } })
      return
    }
    if (mode === 'error') {
      sendJson(response, 503, errorEnvelope())
      return
    }

    const path = url.pathname
    if (path === '/api/health') {
      sendJson(
        response,
        200,
        envelope({
          status: 'ok',
          service: 'silver-pool',
          version: '0.2.0',
          database: { healthy: true, error: null },
        }),
      )
      return
    }
    if (path === '/api/ready') {
      sendJson(
        response,
        200,
        envelope({
          ready: true,
          database: { healthy: true, error: null },
          node: { connected: true, synced: true, initial_block_download: false, error: null },
          stratum: {
            running: true,
            current_job_id: '42',
            template_fresh: true,
            last_template_error: null,
          },
        }),
      )
      return
    }
    if (path === '/api/status') {
      sendJson(
        response,
        200,
        envelope({
          service: 'silver-pool',
          version: '0.2.0',
          ready: true,
          checks: {
            ready: true,
            database: { healthy: true, error: null },
            node: { connected: true, synced: true, initial_block_download: false, error: null },
            stratum: {
              running: true,
              current_job_id: '42',
              template_fresh: true,
              last_template_error: null,
            },
          },
          node: NODE,
          stratum: STRATUM,
          pool: POOL,
          database: { healthy: true },
          timestamp: NOW,
        }),
      )
      return
    }
    if (path === '/api/pool/status') {
      sendJson(
        response,
        200,
        envelope({
          pool: POOL,
          hashrate: { estimate_24h: POOL.estimated_hashrate_24h, unit: 'H/s', window: '24h' },
          recent_blocks: BLOCKS,
          recent_shares: SHARE_ROWS,
          round: ROUND,
          node: NODE,
          stratum: STRATUM,
          config: CONFIG,
        }),
      )
      return
    }
    if (path === '/api/pool/statistics') {
      sendJson(
        response,
        200,
        envelope({
          totals: POOL,
          hashrate: { estimate_24h: POOL.estimated_hashrate_24h, unit: 'H/s', window: '24h' },
        }),
      )
      return
    }
    if (path === '/api/pool/history/hashrate') {
      sendJson(response, 200, envelope(history(url.searchParams.get('range') || '24h')))
      return
    }
    if (path === '/api/pool/miners') {
      const search = (url.searchParams.get('search') || '').toLowerCase()
      const limit = Number(url.searchParams.get('limit') || 50)
      const rows = MINERS.filter((miner) => miner.username.includes(search)).slice(0, limit)
      sendJson(
        response,
        200,
        envelope({ miners: rows, count: rows.length, limit, search: url.searchParams.get('search') || '' }),
      )
      return
    }
    const minerMatch = path.match(/^\/api\/pool\/miner\/([^/]+)(\/shares)?$/)
    if (minerMatch) {
      const username = decodeURIComponent(minerMatch[1])
      const detail = MINER_DETAILS[username]
      if (!detail) {
        sendJson(
          response,
          404,
          {
            ok: false,
            error: { code: 'miner_not_found', message: `miner ${username} was not found` },
            meta: { timestamp: Date.now() / 1000, request_id: 'browser-test' },
          },
        )
        return
      }
      if (minerMatch[2]) {
        const rows = SHARES[username] || []
        sendJson(
          response,
          200,
          envelope({ miner: username, shares: rows, count: rows.length, limit: 50 }),
        )
      } else {
        sendJson(response, 200, envelope(detail))
      }
      return
    }
    if (path === '/api/pool/shares/recent') {
      sendJson(response, 200, envelope({ shares: SHARE_ROWS, count: SHARE_ROWS.length, limit: 20 }))
      return
    }
    if (path === '/api/pool/blocks' || path === '/api/pool/blocks/recent') {
      const status = url.searchParams.get('status') || 'all'
      const limit = Number(url.searchParams.get('limit') || 50)
      const rows = BLOCKS.filter((block) => status === 'all' || block.status === status).slice(0, limit)
      sendJson(response, 200, envelope({ blocks: rows, count: rows.length, limit, status }))
      return
    }
    if (path === '/api/pool/fee-ledger') {
      const rows = [
        {
          block_height: 123,
          block_hash: 'ab'.repeat(32),
          fee_satoshi: 10000000,
          allocated_to_address: 'fee-address',
          status: 'pending',
          created_at: NOW - 90,
        },
      ]
      sendJson(response, 200, envelope({ fee_ledger: rows, count: rows.length, limit: 25 }))
      return
    }
    if (path === '/api/pool/rounds/current') {
      sendJson(response, 200, envelope({ round: ROUND }))
      return
    }
    if (path === '/api/pool/config') {
      sendJson(response, 200, envelope(CONFIG))
      return
    }
    if (path === '/api/docs') {
      sendJson(response, 200, envelope(DOCS))
      return
    }
    if (path === '/api/openapi.json') {
      sendJson(response, 200, {
        openapi: '3.0.3',
        info: { title: 'Silver Pool API', version: '0.2.0' },
        paths: {},
      })
      return
    }
    sendJson(
      response,
      404,
      { ok: false, error: { code: 'not_found', message: 'API endpoint not found' } },
    )
  })
  return {
    server,
    setMode(next) {
      mode = next
    },
    get mode() {
      return mode
    },
  }
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer()
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const port = probe.address().port
      probe.close(() => resolve(port))
    })
  })
}

async function waitForHttp(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return response
    } catch (error) {
      lastError = error
    }
    await delay(150)
  }
  throw new Error(`Timed out waiting for ${url}${lastError ? `: ${lastError.message}` : ''}`)
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

class Cdp {
  constructor(webSocketUrl) {
    this.ws = new WebSocket(webSocketUrl)
    this.nextId = 1
    this.pending = new Map()
    this.handlers = new Map()
    this.ws.addEventListener('message', (event) => {
      const message = JSON.parse(String(event.data))
      if (message.id) {
        const pending = this.pending.get(message.id)
        if (!pending) return
        this.pending.delete(message.id)
        clearTimeout(pending.timer)
        if (message.error) pending.reject(new Error(message.error.message))
        else pending.resolve(message.result)
        return
      }
      const handlers = this.handlers.get(message.method) || []
      for (const handler of handlers) handler(message.params)
    })
  }

  async open() {
    if (this.ws.readyState === WebSocket.OPEN) return
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('CDP websocket open timeout')), 10000)
      this.ws.addEventListener('open', () => {
        clearTimeout(timer)
        resolve()
      })
      this.ws.addEventListener('error', () => {
        clearTimeout(timer)
        reject(new Error('CDP websocket failed'))
      })
    })
  }

  on(method, handler) {
    const handlers = this.handlers.get(method) || []
    handlers.push(handler)
    this.handlers.set(method, handlers)
  }

  send(method, params = {}) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`CDP command timed out: ${method}`))
      }, 20000)
      this.pending.set(id, { resolve, reject, timer })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  close() {
    try {
      this.ws.close()
    } catch {
      // already closed
    }
  }
}

async function startChrome(profileDir) {
  const port = await freePort()
  const process = spawn(
    chromeBin,
    [
      '--headless=new',
      '--no-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--no-first-run',
      '--no-default-browser-check',
      '--hide-scrollbars',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profileDir}`,
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  )
  let stderr = ''
  process.stderr.on('data', (chunk) => {
    stderr += String(chunk)
  })
  await waitForHttp(`http://127.0.0.1:${port}/json/version`)
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
  let page = pages.find((item) => item.type === 'page')
  if (!page) {
    page = await (
      await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })
    ).json()
  }
  return { port, process, page, stderr: () => stderr }
}

describe('Silver Pool multi-page browser behavior', { skip: !chromeBin }, () => {
  let mock
  let mockPort
  let site
  let sitePort
  let chrome
  let cdp
  let baseUrl
  let errors = []
  let tmpRoot

  async function evaluate(expression) {
    const result = await cdp.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    })
    if (result.exceptionDetails) {
      throw new Error(
        result.exceptionDetails.exception?.description ||
          result.exceptionDetails.text ||
          'JavaScript evaluation failed',
      )
    }
    return result.result.value
  }

  async function waitFor(expression, { timeoutMs = 12000, label = expression } = {}) {
    const deadline = Date.now() + timeoutMs
    let lastError
    while (Date.now() < deadline) {
      try {
        if (await evaluate(`Boolean(${expression})`)) return
      } catch (error) {
        lastError = error
      }
      await delay(100)
    }
    throw new Error(
      `Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ''}`,
    )
  }

  const panelReady = `(() => {
    const panel = document.querySelector('[aria-live] .state-panel');
    return document.readyState === 'complete' && panel && !panel.classList.contains('state-loading');
  })()`

  async function navigate(path) {
    const target = new URL(path, baseUrl)
    errors = []
    await cdp.send('Page.navigate', { url: target.href })
    await waitFor(
      `location.href === ${JSON.stringify(target.href)} && document.readyState === 'complete'`,
      { label: `navigation to ${target.href}` },
    )
    await waitFor(panelReady, { label: `page data on ${path}` })
  }

  async function pageInfo() {
    return evaluate(`(() => {
      const active = document.querySelector('[data-nav] a.is-active');
      const panel = document.querySelector('[aria-live] .state-panel');
      return {
        url: location.href,
        title: document.title,
        h1: document.querySelector('main h1')?.textContent.trim() || '',
        bodyPage: document.body.dataset.page || '',
        active: active?.dataset.page || null,
        state: panel ? [...panel.classList].find((name) => name.startsWith('state-') && name !== 'state-panel') : null,
      };
    })()`)
  }

  function assertNoErrors(context) {
    assert.deepEqual(errors, [], `${context} emitted JavaScript errors: ${errors.join(' | ')}`)
  }

  async function setMode(mode) {
    const response = await fetch(`http://127.0.0.1:${mockPort}/__control?mode=${mode}`)
    assert.equal(response.status, 200)
    mock.setMode(mode)
  }

  before(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), 'silver-pool-browser-'))
    mock = createMockApi()
    await new Promise((resolve) => mock.server.listen(0, '127.0.0.1', resolve))
    mockPort = mock.server.address().port

    sitePort = await freePort()
    site = spawn(process.execPath, ['scripts/serve.mjs'], {
      cwd: siteRoot,
      env: {
        ...process.env,
        PORT: String(sitePort),
        API_PROXY: `http://127.0.0.1:${mockPort}`,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    baseUrl = `http://127.0.0.1:${sitePort}`
    await waitForHttp(baseUrl)

    chrome = await startChrome(join(tmpRoot, 'chrome-profile'))
    cdp = new Cdp(chrome.page.webSocketDebuggerUrl)
    await cdp.open()
    cdp.on('Runtime.exceptionThrown', (event) => {
      errors.push(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text || 'exception')
    })
    cdp.on('Runtime.consoleAPICalled', (event) => {
      if (event.type === 'error') {
        errors.push(event.args.map((arg) => arg.value ?? arg.description ?? '').join(' '))
      }
    })
    cdp.on('Log.entryAdded', (event) => {
      if (event.entry?.level === 'error') errors.push(event.entry.text)
    })
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Log.enable')
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    })
  }, { timeout: 60000 })

  after(async () => {
    cdp?.close()
    const exited = new Promise((resolve) => chrome?.process.once('exit', resolve))
    chrome?.process.kill('SIGKILL')
    await Promise.race([exited, delay(5000)])
    site?.kill('SIGKILL')
    mock?.server.close()
    if (tmpRoot) {
      await rm(tmpRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
    }
  })

  test('every page loads directly with the correct title, heading and active navigation', async () => {
    const routes = [
      ['/', 'Overview — Silver Pool', 'overview', 'Mine Bitcoin Silver.'],
      ['/statistics/', 'Statistics — Silver Pool', 'statistics', 'Hashrate and share history'],
      ['/miners/', 'Miners — Silver Pool', 'miners', 'Search the pool'],
      ['/miner/', 'Miner detail — Silver Pool', 'miners', 'Miner and worker records'],
      ['/blocks/', 'Blocks — Silver Pool', 'blocks', 'Blocks found by Silver Pool'],
      ['/getting-started/', 'Getting Started — Silver Pool', 'getting-started', 'Connect a BTCS miner'],
      ['/pool/', 'Pool Configuration — Silver Pool', 'pool', 'Fees, rewards and payout policy'],
      ['/api-docs/', 'API Documentation — Silver Pool', 'api-docs', 'Read-only pool API'],
      ['/status/', 'Service Status — Silver Pool', 'status', 'Is the pool ready?'],
      ['/help/', 'Help & Troubleshooting — Silver Pool', 'help', 'Diagnose a connection problem'],
    ]
    for (const [path, title, active, heading] of routes) {
      await navigate(path)
      const info = await pageInfo()
      assert.equal(info.title, title, `${path} title`)
      assert.equal(info.bodyPage, active, `${path} body page`)
      assert.equal(info.active, active, `${path} active nav`)
      assert.ok(info.h1.includes(heading), `${path} heading was ${info.h1}`)
      assert.ok(
        ['state-ok', 'state-empty'].includes(info.state),
        `${path} should have loaded data, got ${info.state}`,
      )
      assertNoErrors(path)
    }
  })

  test('live API values render on overview, statistics, miners, blocks, config, status and help', async () => {
    await navigate('/')
    const overview = await evaluate(`({
      miners: document.getElementById('stat-miners').textContent,
      endpoint: document.getElementById('hero-endpoint').textContent,
      height: document.getElementById('stat-height').textContent,
      hashrate: document.getElementById('stat-hashrate').textContent,
      state: document.getElementById('overview-state').textContent,
    })`)
    assert.equal(overview.miners, '3')
    assert.equal(overview.endpoint, 'pool.example:3333')
    assert.equal(overview.height, '123')
    assert.match(overview.hashrate, /1\.23 MH\/s/)
    assert.match(overview.state, /Live data loaded/)

    await navigate('/statistics/')
    assert.equal(await evaluate(`document.getElementById('stat-accepted').textContent`), '12')
    assert.match(
      await evaluate(`document.getElementById('chart-state').textContent`),
      /Hashrate history loaded/,
    )

    await navigate('/miners/')
    assert.equal(await evaluate(`document.querySelectorAll('#miners-body tr').length`), 2)
    assert.match(await evaluate(`document.getElementById('miners-body').textContent`), /alice/)
    assert.match(await evaluate(`document.getElementById('miners-body').textContent`), /bob/)

    await navigate('/blocks/')
    assert.equal(await evaluate(`document.querySelectorAll('#blocks-body tr').length`), 1)
    assert.match(await evaluate(`document.getElementById('blocks-body').textContent`), /123/)
    assert.match(await evaluate(`document.getElementById('blocks-body').textContent`), /immature/)

    await navigate('/getting-started/')
    assert.equal(
      await evaluate(`document.getElementById('stratum-endpoint').textContent`),
      'pool.example:3333',
    )
    assert.equal(await evaluate(`document.getElementById('connect-content').hidden`), false)

    await navigate('/pool/')
    assert.equal(await evaluate(`document.getElementById('pool-payouts').textContent`), 'Disabled')
    assert.equal(
      await evaluate(`document.getElementById('pool-endpoint').textContent`),
      'pool.example:3333',
    )

    await navigate('/api-docs/')
    assert.equal(await evaluate(`document.querySelectorAll('#api-endpoints-body tr').length`), 15)
    assert.match(
      await evaluate(`document.getElementById('api-endpoints-body').textContent`),
      /\/api\/health/,
    )

    await navigate('/status/')
    assert.equal(await evaluate(`document.getElementById('check-api').textContent`), 'Online')
    assert.equal(await evaluate(`document.getElementById('check-node').textContent`), 'Synced')
    assert.match(
      await evaluate(`document.getElementById('readiness-banner').textContent`),
      /Pool is ready/,
    )

    await navigate('/help/')
    assert.equal(
      await evaluate(`document.getElementById('help-endpoint').textContent`),
      'pool.example:3333',
    )
    assert.equal(await evaluate(`document.getElementById('help-ready').textContent`), 'Ready for miners')
    assertNoErrors('rendered values')
  })

  test('miner detail renders by query and supports submit, back/forward and refresh', async () => {
    await navigate('/miner/?miner=alice')
    assert.equal(await evaluate(`document.getElementById('miner-name').textContent`), 'alice')
    assert.equal(await evaluate(`document.getElementById('miner-content').hidden`), false)
    assert.equal(await evaluate(`document.title`), 'alice — Silver Pool')
    assert.match(
      await evaluate(`document.getElementById('miner-shares-body').textContent`),
      /accepted/,
    )

    await evaluate(`(() => {
      const input = document.getElementById('miner-search');
      input.value = 'bob';
      document.getElementById('miner-search-form').requestSubmit();
    })()`)
    await waitFor(`location.search === '?miner=bob'`, { label: 'miner history push' })
    await waitFor(`document.getElementById('miner-name').textContent === 'bob'`, {
      label: 'bob miner record',
    })

    await evaluate(`history.back()`)
    await waitFor(`location.search === '?miner=alice'`, { label: 'miner back navigation' })
    await waitFor(`document.getElementById('miner-name').textContent === 'alice'`, {
      label: 'alice restored from history',
    })

    await evaluate(`history.forward()`)
    await waitFor(`location.search === '?miner=bob'`, { label: 'miner forward navigation' })
    await waitFor(`document.getElementById('miner-name').textContent === 'bob'`, {
      label: 'bob restored from history',
    })

    await cdp.send('Page.reload')
    await waitFor(panelReady, { label: 'miner reload' })
    assert.equal(await evaluate(`document.getElementById('miner-name').textContent`), 'bob')
    assertNoErrors('miner search/history')
  })

  test('miners search filters the live table', async () => {
    await navigate('/miners/')
    await evaluate(`(() => {
      const input = document.getElementById('miner-search');
      input.value = 'ali';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`)
    await waitFor(`document.querySelectorAll('#miners-body tr').length === 1`, {
      label: 'filtered miner table',
    })
    assert.match(await evaluate(`document.getElementById('miners-body').textContent`), /alice/)
    assert.doesNotMatch(await evaluate(`document.getElementById('miners-body').textContent`), /bob/)
    assert.match(
      await evaluate(`document.getElementById('miners-count').textContent`),
      /1 miner shown for “ali”/,
    )
    assertNoErrors('miner search')
  })

  test('primary navigation, browser back/forward and reload keep the correct page', async () => {
    await navigate('/')
    await evaluate(`document.querySelector('[data-nav] a[data-page="statistics"]').click()`)
    await waitFor(`location.pathname === '/statistics/'`, { label: 'navigation click' })
    await waitFor(panelReady, { label: 'statistics after click' })
    assert.match(await evaluate(`document.querySelector('main h1').textContent`), /Hashrate/)

    await evaluate(`history.back()`)
    await waitFor(`location.pathname === '/'`, { label: 'back to overview' })
    await waitFor(panelReady, { label: 'overview after back' })
    assert.match(await evaluate(`document.querySelector('main h1').textContent`), /Mine Bitcoin/)

    await evaluate(`history.forward()`)
    await waitFor(`location.pathname === '/statistics/'`, { label: 'forward to statistics' })
    await waitFor(panelReady, { label: 'statistics after forward' })

    await cdp.send('Page.reload')
    await waitFor(panelReady, { label: 'statistics reload' })
    assert.equal(await pageInfo().then((info) => info.active), 'statistics')
    assertNoErrors('history and refresh')
  })

  test('mobile viewport uses the menu toggle without horizontal overflow', async () => {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: true,
    })
    await navigate('/')
    const mobile = await evaluate(`(() => {
      const toggle = document.querySelector('[data-menu-toggle]');
      const nav = document.querySelector('[data-nav]');
      return {
        toggleDisplay: getComputedStyle(toggle).display,
        navDisplay: getComputedStyle(nav).display,
        expanded: toggle.getAttribute('aria-expanded'),
        overflow: document.documentElement.scrollWidth - window.innerWidth,
      };
    })()`)
    assert.notEqual(mobile.toggleDisplay, 'none')
    assert.equal(mobile.navDisplay, 'none')
    assert.equal(mobile.expanded, 'false')
    assert.ok(mobile.overflow <= 1, `horizontal overflow was ${mobile.overflow}px`)

    await evaluate(`document.querySelector('[data-menu-toggle]').click()`)
    await waitFor(
      `document.querySelector('[data-nav]').classList.contains('is-open')`,
      { label: 'mobile menu open' },
    )
    assert.equal(
      await evaluate(`document.querySelector('[data-menu-toggle]').getAttribute('aria-expanded')`),
      'true',
    )
    assert.notEqual(await evaluate(`getComputedStyle(document.querySelector('[data-nav]')).display`), 'none')

    await evaluate(`document.querySelector('[data-nav] a[data-page="help"]').click()`)
    await waitFor(`location.pathname === '/help/'`, { label: 'mobile help navigation' })
    await waitFor(panelReady, { label: 'help page' })
    assert.equal(
      await evaluate(`document.querySelector('[data-nav]').classList.contains('is-open')`),
      false,
    )
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    })
    assertNoErrors('mobile navigation')
  })

  test('API failures produce honest error states on every page', async () => {
    await setMode('error')
    try {
      const checks = [
        ['/', 'state-error', 'stat-miners', '—'],
        ['/statistics/', 'state-error', 'stat-accepted', '—'],
        ['/miners/', 'state-error', 'miners-body', /Miner data is unavailable/],
        ['/blocks/', 'state-error', 'blocks-body', /Block data is unavailable/],
        ['/getting-started/', 'state-error', 'connect-state', /Configuration unavailable/],
        ['/pool/', 'state-error', 'pool-state', /Configuration unavailable/],
        ['/api-docs/', 'state-error', 'api-state', /API documentation unavailable/],
        ['/status/', 'state-error', 'status-state', /Status unavailable/],
        ['/help/', 'state-error', 'help-state', /Live diagnostics unavailable/],
        ['/miner/?miner=alice', 'state-error', 'miner-state', /Miner data unavailable/],
      ]
      for (const [path, state, targetId, expected] of checks) {
        await navigate(path)
        const info = await pageInfo()
        assert.equal(info.state, state, `${path} error state`)
        const target = await evaluate(`document.getElementById(${JSON.stringify(targetId)})?.textContent || ''`)
        if (expected instanceof RegExp) assert.match(target, expected, path)
        else assert.ok(target.includes(expected), `${path} expected ${expected} in ${target}`)
        if (path === '/status/') {
          assert.equal(
            await evaluate(`document.getElementById('check-api').textContent`),
            'Offline',
          )
        }
        if (path === '/help/') {
          assert.equal(
            await evaluate(`document.getElementById('help-endpoint').textContent`),
            'Unavailable',
          )
        }
      }
    } finally {
      await setMode('ok')
    }
  })
})
